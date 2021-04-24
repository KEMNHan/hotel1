from django.db import models


class Guest(models.Model):
    id = models.CharField(primary_key=True, max_length=40)
    name = models.CharField(max_length=20)
    sex = models.BooleanField(default=True)
    age = models.CharField(max_length=10)
    phone = models.CharField(max_length=40)


class Feature(models.Model):
    id = models.CharField(primary_key=True, max_length=40)
    Value = models.TextField(max_length=5000)


class User(models.Model):
    id = models.AutoField(primary_key=True)
    phone = models.CharField(max_length=40)
    password = models.CharField(max_length=40)


class Stay(models.Model):
    id = models.CharField(primary_key=True, max_length=40)
    intime = models.DateTimeField(null=True)
    outtime = models.DateTimeField(null=True)
    room = models.CharField(max_length=10)
    status = models.BooleanField(default=False)
