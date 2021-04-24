from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from face.models import User, Guest, Feature, Stay
from typing import Dict
import yaml
from arcface import ArcFace
from module.face_process import FaceProcess
import os
from django.conf import settings
from datetime import datetime
import recognition

ONE_UNDEAD_THREAD_FLAG = False

def showrtsp(request):
    return render(request, "face/index.html")

def reg(request):
    if request.method == "POST":
        id = request.POST.get('id')
        name = request.POST.get('name')
        sex = request.POST.get('sex')
        phone = request.POST.get('phone')
        age = request.POST.get('age')
        password = request.POST.get('password')
        key_flag = True
        if id == None or name == None or sex == None or phone == None or age == None or password == None:
            key_flag = False
        if key_flag:
            if len(Guest.objects.filter(id=id)) == 0:
                add_user = Guest(id=id, name=name, sex=sex, age=age, phone=phone)
                add_user.save()
                add_user = User(phone=phone, password=password )
                add_user.save()
                return JsonResponse({"status": "BS.200", "msg": "register sucess."})
            else:
                return JsonResponse({"status": "BS.400","message": "Already registered"})
        else:
            return JsonResponse({"status": "BS.400","message": "please check your information"})



def log(request):
    if request.method == "POST":
        phone = request.POST.get('phone')
        password = request.POST.get('password')
        key_flag = True
        if phone == None or password == None:
            key_flag = False
        if key_flag:
            fil = User.objects.filter(phone=phone)
            if len(fil) == 1:
                user = User.objects.get(phone=phone)
                if user.password == password:
                    return JsonResponse({"status": "BS.200", "msg": "log sucess."})
                else:
                    return JsonResponse({"status": "BS.400", "message": "please check your password"})
            else:
                return JsonResponse({"status": "BS.400", "message": "please register first"})
        else:
            return JsonResponse({"status": "BS.400", "message": "please check your phone number and password"})
def check_out(request):
    if request.method == "POST":
        id = request.POST.get('id')
        if id:
            try:
                user = Feature.objects.get(id=id)
                user.delete()
                filename = os.path.join(settings.STATICFILES_DIRS[1], id)
                if os.path.exists(filename):
                    os.remove(filename)
                user = Stay.objects.get(id=id, status=True)
                user.delete()
                return JsonResponse({"status": "BS.200", "msg": "check out sucess."})
            except Feature.DoesNotExist:
                return JsonResponse({"status": "BS.300", "msg": "id is not exists,fail to delete."})
    return JsonResponse({"status": "BS.400", "msg": "please check id."})
def check_in(request):
    if request.method == "POST":
        id = request.POST.get('id')
        pic = request.FILES.get('face')
        room = request.POST.get('room')
        fil = Guest.objects.filter(id=id)

        if len(fil) == 0:
            return JsonResponse({"status": "BS.500", "msg": "no reg"})
        if pic and room:
            filename = os.path.join(settings.STATICFILES_DIRS[1], id)
            with open(filename, 'wb') as f:
                for c in pic.chunks():
                    f.write(c)
            with open("profile.yml", "r", encoding="utf-8") as file:
                profile: Dict[str, str] = yaml.load(file, yaml.Loader)
                ArcFace.APP_ID = profile["app-id"].encode()
                ArcFace.SDK_KEY = profile["sdk-key"].encode()
            face_process = FaceProcess()
            res = face_process.add_person(filename)
            if res[0] == 1 and res[1]:
                add_user = Feature(id=id, Value=res[1])
                add_user.save()
                add_user = Stay(id=id, intime=datetime.now(), outtime=datetime.now(), status=True, room=room)
                add_user.save()

                return JsonResponse({"status": "BS.200", "msg": "check in sucess."})
            else:
                return JsonResponse({"status": "BS.400", "msg": "please check pic"})
        return JsonResponse({"status": "BS.400", "msg": "please check pic"})
def checked_face(request):
    if request.method == "POST":
        id = request.POST.get('id')
        user = Stay.objects.get(id=id)
        roomid = user.room
        print("id: ", id, " room:", roomid)
        return JsonResponse({"status": "BS.200", "msg": "checked face sucess."})


def undeadthread():
    global ONE_UNDEAD_THREAD_FLAG
    if not ONE_UNDEAD_THREAD_FLAG:
        ONE_UNDEAD_THREAD_FLAG = True
    else:
        return

    recognition.runwebsocketserver()

def enable_undeadthread(request):
    import threading
    threading.Thread(target=undeadthread, daemon=True).start()
    return HttpResponse("it works")