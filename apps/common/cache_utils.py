from django.core.cache import cache


def _ver_key(namespace):
    return f'{namespace}:ver'


def versioned_key(namespace, *parts):
    ver = cache.get(_ver_key(namespace), 1)
    return f'{namespace}:v{ver}:' + ':'.join(str(p) for p in parts)


def bump_version(namespace):
    try:
        cache.incr(_ver_key(namespace))
    except ValueError:
        cache.set(_ver_key(namespace), 2, None)