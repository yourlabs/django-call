# flake8: noqa: D*
import os
from crudlfap.settings import *

DEBUG = True

ROOT_URLCONF = 'djcall_example.urls'

INSTALLED_APPS += ['djcall']

STATIC_ROOT = 'static'
