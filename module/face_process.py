import base64
import logging
import os
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Dict, Tuple, Generator, Optional
import numpy as np
from arcface import ArcFace, image_regularization, Rect
from arcface import FaceInfo as ArcFaceInfo
from arcface import Gender
from module.image_source import get_regular_file, read_image
import pymysql
import yaml
import time
import requests

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.DEBUG)
class FaceInfo:
    def __init__(self, arc_face_info: ArcFaceInfo):
        self.stop_flags = [True, True]
        self.arc_face_info: ArcFaceInfo = arc_face_info
        self._image = np.array([])
        self.name = ""
        self.threshold: float = 0.0
        self.liveness = None
        self.age = None
        self.gender = None
    @property
    def image(self):
        return self._image
    @image.setter
    def image(self, image: np.ndarray):
        self._image = image.copy()
        # self._image = capture_image(image, self.rect)
    @property
    def rect(self):
        return self.arc_face_info.rect
    def need_update(self) -> bool:
        """
        :return:
        """
        # id = self.arc_face_info.face_id
        # busy = self._busy()
        # fs = self.futures
        # flags = fs[0].done() if fs[0] is not None else None, fs[1].done() if fs[1] is not None else None
        # _logger.debug("%s busy %s %s" % (self.arc_face_info.face_id, self._busy(), flags))
        return not any((
            self.rect.size < (50, 50),
            self._busy(),
            self.complete(),
        ))
    def cancel(self) -> None:
        """
        取消获取当前的信息
        :return: None
        """
        self.stop_flags[0] = True
        self.stop_flags[1] = True
    def complete(self) -> bool:
        """
        判断人脸所有可显示的信息是否都存在了
        :return: 所有信息都存在返回 True，否则返回 False
        """
        return all((
            bool(self.name),
            self.liveness is not None,
            self.age is not None,
            self.gender is not None,
        ))
    def _busy(self) -> bool:
        """
        判断是否在更新信息
        :return: 所有线程都在工作返回 True, 否则返回 False
        """
        return all(map(lambda x: not x, self.stop_flags))
    def __str__(self):
        to_str = FaceInfo._to_str
        return "%s,%s,%s,%s,%s" % (
            self.name,
            to_str(self.threshold, bool(self.name), "%.2f" % self.threshold, ""),
            to_str(self.liveness, self.liveness, "真", "假"),
            to_str(self.gender, self.gender == Gender.Male, "男", "女"),
            to_str(self.age, True, self.age, self.age)
        )
    @staticmethod
    def _to_str(v, condition, v1, v2):
        if v is None:
            return ""
        else:
            return v1 if condition else v2

class FaceProcess:
    def __init__(self):
        self._arcface = ArcFace(ArcFace.IMAGE_MODE)
        self._features: Dict[str, bytes] = {}  # 人脸数据库
        # max_workers 必须为 1，因为 SDK 对并行的支持有限
        self._executors = (ThreadPoolExecutor(max_workers=1), ThreadPoolExecutor(max_workers=1))
        self.close_update_feature = True
        self.count = 0
    def async_update_face_info(self, image: np.ndarray, face_info: FaceInfo) -> None:
        """
        更新单个人脸的信息。
        :param image: 包含人脸的图片
        :param face_info: 人脸信息
        :return: None
        """
        _logger.info("人脸 %d: 开始获取信息" % face_info.arc_face_info.face_id)
        face_info.image = image
        if face_info.stop_flags[0]:
            _logger.debug("人脸 %d: 获取姓名" % face_info.arc_face_info.face_id)
            face_info.stop_flags[0] = False
            future: Future = self._executors[0].submit(self._update_name, face_info)
            future.add_done_callback(lambda x: FaceProcess._update_name_done(face_info, x))

        if face_info.stop_flags[1]:
            _logger.debug("人脸 %d: 活体检测、性别、年龄" % face_info.arc_face_info.face_id)
            face_info.stop_flags[1] = False
            future: Future = self._executors[1].submit(self._update_other, face_info)
            future.add_done_callback(lambda x: FaceProcess._update_other_done(face_info, x))
    def _update_other(self, face_info: FaceInfo) -> Tuple[Optional[bool], Optional[int], Optional[Gender]]:
        """
        更新其它信息，比如 活体、性别、年龄
        :param face_info:
        :return: 识别成功的信息数
        """
        image, orient = face_info.image, face_info.arc_face_info.orient
        face_id = face_info.arc_face_info.face_id
        arc_face_info = face_info.arc_face_info
        if face_info.stop_flags[1]:
            return None, None, None
        if not self._arcface.process_face(
                image,
                arc_face_info,
                ArcFace.LIVENESS | ArcFace.AGE | ArcFace.GENDER
        ):
            _logger.debug("人脸 %d: 处理失败" % face_id)
            return None, None, None
        arcface = self._arcface
        return arcface.is_liveness(), arcface.get_age(), arcface.get_gender()
    @staticmethod
    def _update_other_done(face_info: FaceInfo, future: Future):
        face_info.liveness, face_info.age, face_info.gender = future.result()
        face_info.stop_flags[1] = True
    def _update_name(self, face_info: FaceInfo) -> Tuple[str, float]:
        """
        提取特征，再在人脸数据库查找符合条件的特征
        :return: 成功返回 True，失败返回 False
        """
        image, orient = face_info.image, face_info.arc_face_info.orient
        face_id = face_info.arc_face_info.face_id
        arc_face_info = face_info.arc_face_info
        feature = self._arcface.extract_feature(image, arc_face_info)
        if not feature:
            _logger.debug("人脸 %d: 提取特征值失败(%s)" % (face_id, "%dx%d" % face_info.rect.size))
            return "", 0.0

        if face_info.stop_flags[0]:
            _logger.debug("人脸 %d: 取消识别人脸" % face_id)
            return "", 0.0

        max_threshold = 0.0
        opt_name = ""
        for name, feature_ in self._features.items():
            threshold = self._arcface.compare_feature(feature, feature_)
            if max_threshold < threshold:
                max_threshold = threshold
                opt_name = name
        #相似度阈值
        if 0.6 < max_threshold:
            _logger.debug("人脸 %d: 识别成功，与 %s 相似度 %.2f" % (face_id, opt_name, max_threshold))
            url = "http://127.0.0.1:8000/checkedface/"
            info = {'id': opt_name}
            r = requests.post(url, data=info)

            return opt_name, max_threshold
        _logger.debug("人脸 %d: 识别失败，与最像的 %s 的相似度 %.2f" % (face_id, opt_name, max_threshold))
        return "", 0.0
    @staticmethod
    def _update_name_done(face_info: FaceInfo, future: Future):
        face_info.name, face_info.threshold = future.result()
        face_info.stop_flags[0] = True


    def load_features(self) -> int:
        """
        从数据库加载数据
        :param filename: 保存人脸数据库的文件名
        :return: 加载的人脸数
        """
        while True:
            with open("profile.yml", "r", encoding="utf-8") as file:
                profile: Dict[str, str] = yaml.load(file, yaml.Loader)
                server_on = profile["server-on"].encode()
                host = profile["database"]["host"].encode()
                user = profile["database"]["user"].encode()
                password = profile["database"]["password"].encode()
                base = profile["database"]["base"].encode()

            if server_on == 0:
                break
            conn = pymysql.connect(host, user, password, base, charset='utf8')
            cursor = conn.cursor()
            sql = "SELECT * FROM FACE_FEATURE"
            self.count = 0
            try:
                cursor.execute(sql)
                # 获取所有记录列表
                results = cursor.fetchall()
                for row in results:
                    id = row[0]
                    feature = base64.b64decode(row[1])
                    self._features[id] = feature
                    self.count += 1
            except:
                print("Error: unable to fecth data")
            conn.close()
            _logger.info("从数据库中加载了 %d 个特征值" % (self.count))
            time.sleep(30)


    def add_person(self, filename: str):
        features = {}
        name: str = os.path.basename(filename)
        name: str = name.split(".")[0]
        faces_number, features_ = self._load_features_from_image(name, read_image(filename))
        if faces_number == 1:
            features.update(features_)
            for name, feature in features_.items():
                return faces_number, base64.b64encode(feature).decode()
        self._features.update(features)
        return faces_number, "None"

    def _load_features_from_image(self, name: str, image: np.ndarray) -> Tuple[int, Dict[str, bytes]]:
        """
        从图片中加载特征值
        如果 name 为空，名字按数字编号来
        否则，如果只有一个特征，使用 name 的值作为名称
        否则，使用 <name-数字编号> 来命名
        :param name: 图片中人的名字
        :param image: 需要提取特征的图片
        :return: 总的人脸数（包含不清晰无法提取特征值的人脸）, Dict[姓名, 特征值]
        """
        if image.size == 0:
            return 0, {}
        image = image_regularization(image)
        # 检测人脸位置
        faces = self._arcface.detect_faces(image)
        # 提取所有人脸特征
        features = map(lambda x: self._arcface.extract_feature(image, x), faces)
        # 删除空的人脸特征
        features = list(filter(lambda feature: feature, features))

        # 按一定规则生成名字
        def get_name() -> Generator[str, None, None]:
            for i in range(len(features)):
                if len(name) == 0:
                    yield "%d" % i
                if len(features) == 1:
                    yield name
                else:
                    yield "%s-%d" % (name, i)

        # 将所有特征和名字拼接起来
        def assemble() -> Dict[str, bytes]:
            res = {}
            for name_, feature in zip(get_name(), features):
                res[name_] = feature
            return res

        return len(faces), assemble()
    def release(self):
        for executor in self._executors:
            executor.shutdown()
        self._arcface.release()
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()



