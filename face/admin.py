from django.contrib import admin

from . import models	# 导入当前文件夹下的models文件
admin.site.register(models.User),	#
admin.site.register(models.Guest),
admin.site.register(models.Feature),
admin.site.register(models.Stay)
