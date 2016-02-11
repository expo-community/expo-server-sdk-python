__version__ = '0.0.1'

import json

import requests

class Push(object):
    """Push Notifications"""

    @classmethod
    def is_exponent_push_token(cls, token):
        """Returns `True` if the token is an Exponent push token"""

        return (type(token) is str) and token.startswith('ExponentPushToken')

class Client(object):
    """Client stuff"""

    @classmethod
    def publish(options={}):
        data = options['data']
        del options['data']
        # TODO: Finish this
        response = requests.post("https://exp.host/--/api/notify/")

class InvalidPushTokenError(Exception):
    """Raised when a push token is not a valid ExponentPushToken"""

    pass
