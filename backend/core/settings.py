import os
from pathlib import Path
import certifi
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR.parent

load_dotenv(PROJECT_DIR / '.env')
os.environ.setdefault('SSL_CERT_FILE', certifi.where())

def _env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ('1', 'true', 'yes', 'on')


def _env_list(name, default=''):
    value = os.environ.get(name, default)
    return [item.strip() for item in value.split(',') if item.strip()]


# 檢查基本資料
DEBUG = _env_bool('DJANGO_DEBUG', False)
ALLOWED_HOSTS = _env_list(
    'DJANGO_ALLOWED_HOSTS',
    'localhost,127.0.0.1',
)

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')

if not SECRET_KEY:
    raise RuntimeError("無法讀取 DJANGO_SECRET_KEY，請檢查 .env")



INSTALLED_APPS = [
    'daphne',  # 必須放在第一個
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'corsheaders',
    'game',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware', # 放在最上面
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = _env_list(
    'DJANGO_CORS_ALLOWED_ORIGINS',
    'http://localhost:5173,http://127.0.0.1:5173',
)
CSRF_TRUSTED_ORIGINS = _env_list(
    'DJANGO_CSRF_TRUSTED_ORIGINS',
    'http://localhost:5173,http://127.0.0.1:5173',
)
ROOT_URLCONF = 'core.urls'
ASGI_APPLICATION = 'core.asgi.application'
REDIS_URL = os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/0')

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

LANGUAGE_CODE = 'zh-hant'
TIME_ZONE = 'Asia/Taipei'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = os.environ.get('DJANGO_STATIC_ROOT', BASE_DIR / 'staticfiles')
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

SESSION_COOKIE_SECURE = _env_bool('DJANGO_SESSION_COOKIE_SECURE', False)
CSRF_COOKIE_SECURE = _env_bool('DJANGO_CSRF_COOKIE_SECURE', False)
SECURE_SSL_REDIRECT = _env_bool('DJANGO_SECURE_SSL_REDIRECT', False)
if _env_bool('DJANGO_SECURE_PROXY_SSL_HEADER', False):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Terminal email output for local development.
# EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
# DEFAULT_FROM_EMAIL = 'noreply@example.com'

# Gmail SMTP email output. Fill EMAIL_HOST_USER and EMAIL_HOST_PASSWORD in .env.
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_BACKEND = os.environ.get(
    'EMAIL_BACKEND',
    'django.core.mail.backends.smtp.EmailBackend'
    if EMAIL_HOST_USER and EMAIL_HOST_PASSWORD
    else 'django.core.mail.backends.console.EmailBackend',
)
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True') == 'True'
DEFAULT_FROM_EMAIL = os.environ.get(
    'DEFAULT_FROM_EMAIL',
    EMAIL_HOST_USER or 'noreply@example.com',
)
FRONTEND_BASE_URL = os.environ.get('FRONTEND_BASE_URL', 'http://127.0.0.1:5173')

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

CHANNEL_LAYER_BACKEND = os.environ.get('CHANNEL_LAYER_BACKEND', 'redis').lower()

if CHANNEL_LAYER_BACKEND == 'inmemory':
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        },
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [REDIS_URL],
                "capacity": 1500,  
                "expiry": 10,      
            },
        },
    }
