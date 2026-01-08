"""
Django test settings for sagaz integration tests.
"""

SECRET_KEY = 'test-secret-key-for-testing-only'

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Sagaz settings
SAGAZ = {
    'STORAGE_BACKEND': 'memory',
}

USE_TZ = True
