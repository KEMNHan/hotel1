import argparse
import logging
import threading
import time
from typing import Dict, Generator
import cv2 as cv
import numpy as np
import yaml
from arcface import ArcFace, timer
from arcface import FaceInfo as ArcFaceInfo
from module.face_process import FaceProcess, FaceInfo
from module.text_renderer import put_text
from websocket_server import WebsocketServer
from module.image_source import ImageSource, LocalCamera
import base64

def runwebsocketserver():
    _logger = logging.getLogger(__name__)
    camera = None
    frame = None
    def _frame_rate_statistics_generator() -> Generator[float, bool, None]:
        """
        统计视频帧率
        :return:
        """
        count = 0
        begin_time = time.time()
        break_ = False
        while not break_:
            if count != 100:
                fps = 0.0
            else:
                end_time = time.time()
                fps = count / (end_time - begin_time)
                count = 0
                begin_time = time.time()
            count += 1
            break_ = yield fps

    def _draw_face_info(image: np.ndarray, face_info: FaceInfo) -> None:
        """
        将人脸的信息绘制到屏幕上
        :param face_info: 人脸信息
        :return: None
        """
        # 绘制人脸位置
        rect = face_info.rect
        color = (255, 0, 0) if face_info.name else (0, 0, 255)
        cv.rectangle(image, rect.top_left, rect.bottom_right, color, 2)
        # 绘制人的其它信息
        x, y = rect.top_middle
        put_text(image, "%s" % face_info, bottom_middle=(x, y - 2))
        # 绘制人脸 ID
        info = "%d" % face_info.arc_face_info.face_id
        x, y = rect.top_left
        put_text(image, info, left_top=(x + 2, y + 2))

    def _show_image(image: np.ndarray) -> int:
        global frame
        frame = image
        #cv.imshow("ArcFace Demo", image)
        #cv.waitKey(1)
        with open("profile.yml", "r", encoding="utf-8") as file:
            profile: Dict[str, str] = yaml.load(file, yaml.Loader)
            server_on = profile["server-on"].encode()
        if server_on == 0:
            return True
        return False

    @timer(output=_logger.info)
    def _run_1_n(image_source: ImageSource, face_process: FaceProcess) -> None:
        """
        1:n 的整个处理的逻辑
        :image_source: 识别图像的源头
        :face_process: 用来对人脸信息进行提取
        :return: None
        """
        with ArcFace(ArcFace.VIDEO_MODE) as arcface:
            cur_face_info = None  # 当前的人脸
            frame_rate_statistics = _frame_rate_statistics_generator()
            while True:
                # 获取视频帧
                image = image_source.read()
                # 检测人脸
                faces_pos = arcface.detect_faces(image)
                if len(faces_pos) == 0:
                    # 图片中没有人脸
                    cur_face_info = None
                else:
                    # 使用曼哈顿距离作为依据找出最靠近中心的人脸
                    center_y, center_x = image.shape[:2]
                    center_y, center_x = center_y // 2, center_x // 2
                    center_face_index = -1
                    min_center_distance = center_x + center_y + 4
                    cur_face_index = -1
                    for i, pos in enumerate(faces_pos):
                        if cur_face_info is not None and pos.face_id == cur_face_info.arc_face_info.face_id:
                            cur_face_index = i
                            break
                        x, y = pos.rect.center
                        if x + y < min_center_distance:
                            center_face_index = i
                            min_center_distance = x + y
                    if cur_face_index != -1:
                        # 上一轮的人脸依然在，更新位置信息
                        cur_face_info.arc_face_info = faces_pos[cur_face_index]
                    else:
                        # 上一轮的人脸不在了，选择当前所有人脸的最大人脸
                        cur_face_info = FaceInfo(faces_pos[center_face_index])
                if cur_face_info is not None:
                    # 异步更新人脸的信息
                    if cur_face_info.need_update():
                        face_process.async_update_face_info(image, cur_face_info)
                    # 绘制人脸信息
                    _draw_face_info(image, cur_face_info)
                    # 绘制中心点
                    # put_text(image, "x", bottom_middle=(center_x, center_y))
                # 显示到界面上
                if _show_image(image):
                    break
                # 统计帧率
                fps = next(frame_rate_statistics)
                if fps:
                    _logger.info("FPS: %.2f" % fps)

    @timer(output=_logger.info)
    def _run_m_n(image_source: ImageSource, face_process: FaceProcess) -> None:
        with ArcFace(ArcFace.VIDEO_MODE) as arcface:
            faces_info: Dict[int, FaceInfo] = {}
            frame_rate_statistics = _frame_rate_statistics_generator()
            while True:
                # 获取视频帧
                image = image_source.read()
                # 检测人脸
                faces_pos: Dict[int, ArcFaceInfo] = {}
                for face_pos in arcface.detect_faces(image):
                    faces_pos[face_pos.face_id] = face_pos
                # 删除过期 id, 添加新的 id
                cur_faces_id = faces_pos.keys()
                last_faces_id = faces_info.keys()
                for face_id in last_faces_id - cur_faces_id:
                    faces_info[face_id].cancel()  # 如果有操作在进行，这将取消操作
                    faces_info.pop(face_id)
                for face_id in cur_faces_id:
                    if face_id in faces_info:
                        # 人脸已经存在，只需更新位置就好了
                        faces_info[face_id].arc_face_info = faces_pos[face_id]
                    else:
                        faces_info[face_id] = FaceInfo(faces_pos[face_id])

                # 更新人脸的信息
                # for face_info in faces_info:
                #     face_process.async_update_face_info(image, face_info)
                opt_face_info = None
                for face_info in filter(lambda x: x.need_update(), faces_info.values()):
                    if opt_face_info is None or opt_face_info.rect.size < face_info.rect.size:
                        opt_face_info = face_info

                if opt_face_info is not None:
                    face_process.async_update_face_info(image, opt_face_info)
                # 绘制人脸信息
                for face_info in faces_info.values():
                    _draw_face_info(image, face_info)

                if _show_image(image):
                    break
                # 统计帧率
                fps = next(frame_rate_statistics)
                if fps:
                    _logger.info("FPS: %.2f" % fps)

    def new_client(client, server):
        print("New client connected and was given id %d" % client['id'])
        # 发送给所有的连接
        server.send_message_to_all("Hey all, a new client has joined us")

    def client_left(client, server):
        id = 1
        #print("Client(%d) disconnected" % client['id'])

    def message_received(client, server, message):
        if len(message) > 200:
            message = message[:200] + '..'
        print("Client(%d) said: %s" % (client['id'], message))
        #with open("profile.yml", "r", encoding="utf-8") as file:
        #    profile: Dict[str, str] = yaml.load(file, yaml.Loader)
        #    rtsp = profile["camera"][message].encode().decode("gbk", "strict")
        #global camera
        #camera.set_camera(rtsp)
        # 发送给所有的连接

    def from_vedio():
        thread2 = threading.Thread(target=face_recognition, args=(1,))
        thread2.start()
        thread1 = threading.Thread(target=vedio_send, args=(1,))
        thread1.start()
        print('webserver start')

    def vedio_send(n):
        global frame
        while True:
            with open("profile.yml", "r", encoding="utf-8") as file:
                profile: Dict[str, str] = yaml.load(file, yaml.Loader)
                server_on = profile["server-on"].encode()
            if server_on == 0:
                break
            if len(server.clients) > 0:
                image = cv.imencode('.jpg', frame)[1]
                base64_data = base64.b64encode(image)
                s = base64_data.decode()
                # print('data:image/jpeg;base64,%s'%s)
                server.send_message_to_all('data:image/jpeg;base64,%s' % s)
            time.sleep(0.01)

    def face_recognition(n):
        global camera
        camera = LocalCamera()
        with open("profile.yml", "r", encoding="utf-8") as file:
            profile: Dict[str, str] = yaml.load(file, yaml.Loader)
            ArcFace.APP_ID = profile["app-id"].encode()
            ArcFace.SDK_KEY = profile["sdk-key"].encode()
        face_process = FaceProcess()

        class AutoCloseOpenCVWindows:
            def __enter__(self):
                pass

            def __exit__(self, exc_type, exc_val, exc_tb):
                cv.destroyAllWindows()

        """
            加载人脸部分
            逻辑->30s刷新一次feature
        """
        update_feature = threading.Thread(target=face_process.load_features)
        update_feature.start()
        with face_process, AutoCloseOpenCVWindows():
            run = _run_m_n #_run_1_n if args.single
            with camera:
                run(camera, face_process)

    server = WebsocketServer(port=8124, host='127.0.0.1')
    from_vedio()
    # 有设备连接上了
    server.set_fn_new_client(new_client)
    # 断开连接
    server.set_fn_client_left(client_left)
    # 接收到信息
    server.set_fn_message_received(message_received)
    # 开始监听
    server.run_forever()

if __name__ == "__main__":

    runwebsocketserver()
    #face_recognition()


