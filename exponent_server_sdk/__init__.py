from collections import namedtuple
import json
import itertools
import requests


class PushTicketError(Exception):
    """Base class for all push ticket errors"""
    def __init__(self, push_response):
        if push_response.message:
            self.message = push_response.message
        else:
            self.message = 'Unknown push ticket error'
        super(PushTicketError, self).__init__(self.message)

        self.push_response = push_response


class DeviceNotRegisteredError(PushTicketError):
    """Raised when the push token is invalid

    To handle this error, you should stop sending messages to this token.
    """
    pass


class MessageTooBigError(PushTicketError):
    """Raised when the notification was too large.

    On Android and iOS, the total payload must be at most 4096 bytes.
    """
    pass


class MessageRateExceededError(PushTicketError):
    """Raised when you are sending messages too frequently to a device

    You should implement exponential backoff and slowly retry sending messages.
    """
    pass


class InvalidCredentialsError(PushTicketError):
    """Raised when our push notification credentials for your standalone app 
    are invalid (ex: you may have revoked them).

    Run expo build:ios -c to regenerate new push notification credentials for
    iOS. If you revoke an APN key, all apps that rely on that key will no
    longer be able to send or receive push notifications until you upload a
    new key to replace it. Uploading a new APN key will not change your users'
    Expo Push Tokens.
    """
    pass


class PushServerError(Exception):
    """Raised when the push token server is not behaving as expected

    For example, invalid push notification arguments result in a different
    style of error. Instead of a "data" array containing errors per
    notification, an "error" array is returned.

    {"errors": [
      {"code": "API_ERROR",
       "message": "child \"to\" fails because [\"to\" must be a string]. \"value\" must be an array."
      }
    ]}
    """
    def __init__(self, message, response, response_data=None, errors=None):
        self.message = message
        self.response = response
        self.response_data = response_data
        self.errors = errors
        super(PushServerError, self).__init__(self.message)


class PushMessage(
        namedtuple('PushMessage', [
            'to', 'data', 'title', 'body', 'sound', 'ttl', 'expiration',
            'priority', 'badge', 'category', 'display_in_foreground',
            'channel_id', 'subtitle', 'mutable_content'
        ])):
    """An object that describes a push notification request.

    You can override this class to provide your own custom validation before
    sending these to the Exponent push servers. You can also override the
    get_payload function itself to take advantage of any hidden or new
    arguments before this library updates upstream.

        Args:
            to: A token of the form ExponentPushToken[xxxxxxx]
            data: A dict of extra data to pass inside of the push notification.
                The total notification payload must be at most 4096 bytes.
            title: The title to display in the notification. On iOS, this is
                displayed only on Apple Watch.
            body: The message to display in the notification.
            sound: A sound to play when the recipient receives this
                notification. Specify "default" to play the device's default
                notification sound, or omit this field to play no sound.
            ttl: The number of seconds for which the message may be kept around
                for redelivery if it hasn't been delivered yet. Defaults to 0.
            expiration: UNIX timestamp for when this message expires. It has
                the same effect as ttl, and is just an absolute timestamp
                instead of a relative one.
            priority: Delivery priority of the message. 'default', 'normal',
                and 'high' are the only valid values.
            badge: An integer representing the unread notification count. This
                currently only affects iOS. Specify 0 to clear the badge count.
            category: ID of the Notification Category through which to display
                 this notification.
            channel_id: ID of the Notification Channel through which to display
                this notification on Android devices.
            display_in_foreground: Displays the notification when the app is
                foregrounded. Defaults to `false`. No longer available?
            subtitle: The subtitle to display in the notification below the 
                title (iOS only).
            mutable_content: Specifies whether this notification can be 
                intercepted by the client app. In Expo Go, defaults to true.
                In standalone and bare apps, defaults to false. (iOS Only)

    """
    def get_payload(self):
        # Sanity check for invalid push token format.
        if not PushClient.is_exponent_push_token(self.to):
            raise ValueError('Invalid push token')

        # There is only one required field.
        payload = {
            'to': self.to,
        }

        # All of these fields are optional.
        if self.data is not None:
            payload['data'] = self.data
        if self.title is not None:
            payload['title'] = self.title
        if self.body is not None:
            payload['body'] = self.body
        if self.ttl is not None:
            payload['ttl'] = self.ttl
        if self.expiration is not None:
            payload['expiration'] = self.expiration
        if self.priority is not None:
            payload['priority'] = self.priority
        if self.subtitle is not None:
            payload['subtitle'] = self.subtitle
        if self.sound is not None:
            payload['sound'] = self.sound
        if self.badge is not None:
            payload['badge'] = self.badge
        if self.channel_id is not None:
            payload['channelId'] = self.channel_id
        if self.category is not None:
            payload['categoryId'] = self.category
        if self.mutable_content is not None:
            payload['mutableContent'] = self.mutable_content

        # here for legacy reasons
        if self.display_in_foreground is not None:
            payload['_displayInForeground'] = self.display_in_foreground
        return payload


# Allow optional arguments for PushMessages since everything but the `to` field
# is optional. Unfortunately namedtuples don't allow for an easy way to create
# a required argument at the constructor level right now.
PushMessage.__new__.__defaults__ = (None, ) * len(PushMessage._fields)


class PushTicket(
        namedtuple('PushTicket',
                   ['push_message', 'status', 'message', 'details', 'id'])):
    """Wrapper class for a push notification response.

    A successful single push notification:
        {'status': 'ok'}

    An invalid push token
        {'status': 'error',
         'message': '"adsf" is not a registered push notification recipient'}
    """
    # Known status codes
    ERROR_STATUS = 'error'
    SUCCESS_STATUS = 'ok'

    # Known error strings
    ERROR_DEVICE_NOT_REGISTERED = 'DeviceNotRegistered'
    ERROR_MESSAGE_TOO_BIG = 'MessageTooBig'
    ERROR_MESSAGE_RATE_EXCEEDED = 'MessageRateExceeded'

    def is_success(self):
        """Returns True if this push notification successfully sent."""
        return self.status == PushTicket.SUCCESS_STATUS

    def validate_response(self):
        """Raises an exception if there was an error. Otherwise, do nothing.

        Clients should handle these errors, since these require custom handling
        to properly resolve.
        """
        if self.is_success():
            return

        # Handle the error if we have any information
        if self.details:
            error = self.details.get('error', None)

            if error == PushTicket.ERROR_DEVICE_NOT_REGISTERED:
                raise DeviceNotRegisteredError(self)
            elif error == PushTicket.ERROR_MESSAGE_TOO_BIG:
                raise MessageTooBigError(self)
            elif error == PushTicket.ERROR_MESSAGE_RATE_EXCEEDED:
                raise MessageRateExceededError(self)

        # No known error information, so let's raise a generic error.
        raise PushTicketError(self)


class PushReceipt(
        namedtuple('PushReceipt', ['id', 'status', 'message', 'details'])):
    """Wrapper class for a PushReceipt response. Similar to a PushResponse

    A successful single push notification:
        'data': {
            'id': {'status': 'ok'}
        }
    Errors contain 'errors'

    """
    # Known status codes
    ERROR_STATUS = 'error'
    SUCCESS_STATUS = 'ok'

    # Known error strings
    ERROR_DEVICE_NOT_REGISTERED = 'DeviceNotRegistered'
    ERROR_MESSAGE_TOO_BIG = 'MessageTooBig'
    ERROR_MESSAGE_RATE_EXCEEDED = 'MessageRateExceeded'
    INVALID_CREDENTIALS = 'InvalidCredentials'

    def is_success(self):
        """Returns True if this push notification successfully sent."""
        return self.status == PushReceipt.SUCCESS_STATUS

    def validate_response(self):
        """Raises an exception if there was an error. Otherwise, do nothing.

        Clients should handle these errors, since these require custom handling
        to properly resolve.
        """
        if self.is_success():
            return

        # Handle the error if we have any information
        if self.details:
            error = self.details.get('error', None)

            if error == PushReceipt.ERROR_DEVICE_NOT_REGISTERED:
                raise DeviceNotRegisteredError(self)
            elif error == PushReceipt.ERROR_MESSAGE_TOO_BIG:
                raise MessageTooBigError(self)
            elif error == PushReceipt.ERROR_MESSAGE_RATE_EXCEEDED:
                raise MessageRateExceededError(self)
            elif error == PushReceipt.INVALID_CREDENTIALS:
                raise InvalidCredentialsError(self)

        # No known error information, so let's raise a generic error.
        raise PushTicketError(self)


class PushClient(object):
    """Exponent push client

    See full API docs at https://docs.expo.io/versions/latest/guides/push-notifications.html#http2-api
    """
    DEFAULT_HOST = "https://exp.host"
    DEFAULT_BASE_API_URL = "/--/api/v2"
    DEFAULT_MAX_MESSAGE_COUNT = 100
    DEFAULT_MAX_RECEIPT_COUNT = 1000

    def __init__(self, host=None, api_url=None, session=None, **kwargs):
        """Construct a new PushClient object.

        Args:
            host: The server protocol, hostname, and port.
            api_url: The api url at the host.
            session: Pass in your own requests.Session object if you prefer 
                to customize
        """
        self.host = host
        if not self.host:
            self.host = PushClient.DEFAULT_HOST

        self.api_url = api_url
        if not self.api_url:
            self.api_url = PushClient.DEFAULT_BASE_API_URL

        self.max_message_count = kwargs[
            'max_message_count'] if 'max_message_count' in kwargs else PushClient.DEFAULT_MAX_MESSAGE_COUNT
        self.max_receipt_count = kwargs[
            'max_receipt_count'] if 'max_receipt_count' in kwargs else PushClient.DEFAULT_MAX_RECEIPT_COUNT
        self.timeout = kwargs['timeout'] if 'timeout' in kwargs else None

        self.session = session
        if not self.session:
            self.session = requests.Session()
            self.session.headers.update({
                'accept': 'application/json',
                'accept-encoding': 'gzip, deflate',
                'content-type': 'application/json',
            })

    @classmethod
    def is_exponent_push_token(cls, token):
        """Returns `True` if the token is an Exponent push token"""
        import six

        return (isinstance(token, six.string_types)
                and token.startswith('ExponentPushToken'))

    def _publish_internal(self, push_messages):
        """Send push notifications

        The server will validate any type of syntax errors and the client will
        raise the proper exceptions for the user to handle.

        Each notification is of the form:
        {
          'to': 'ExponentPushToken[xxx]',
          'body': 'This text gets display in the notification',
          'badge': 1,
          'data': {'any': 'json object'},
        }

        Args:
            push_messages: An array of PushMessage objects.
        """

        response = self.session.post(
            self.host + self.api_url + '/push/send',
            data=json.dumps([pm.get_payload() for pm in push_messages]),
            timeout=self.timeout)

        # Let's validate the response format first.
        try:
            response_data = response.json()
        except ValueError:
            # The response isn't json. First, let's attempt to raise a normal
            # http error. If it's a 200, then we'll raise our own error.
            response.raise_for_status()

            raise PushServerError('Invalid server response', response)

        # If there are errors with the entire request, raise an error now.
        if 'errors' in response_data:
            raise PushServerError('Request failed',
                                  response,
                                  response_data=response_data,
                                  errors=response_data['errors'])

        # We expect the response to have a 'data' field with the responses.
        if 'data' not in response_data:
            raise PushServerError('Invalid server response',
                                  response,
                                  response_data=response_data)

        # Use the requests library's built-in exceptions for any remaining 4xx
        # and 5xx errors.
        response.raise_for_status()

        # Sanity check the response
        if len(push_messages) != len(response_data['data']):
            raise PushServerError(
                ('Mismatched response length. Expected %d %s but only '
                 'received %d' %
                 (len(push_messages), 'receipt' if len(push_messages) == 1 else
                  'receipts', len(response_data['data']))),
                response,
                response_data=response_data)

        # At this point, we know it's a 200 and the response format is correct.
        # Now let's parse the responses(push_tickets) per push notification.
        push_tickets = []
        for i, push_ticket in enumerate(response_data['data']):
            push_tickets.append(
                PushTicket(
                    push_message=push_messages[i],
                    # If there is no status, assume error.
                    status=push_ticket.get('status', PushTicket.ERROR_STATUS),
                    message=push_ticket.get('message', ''),
                    details=push_ticket.get('details', None),
                    id=push_ticket.get('id', '')))

        return push_tickets

    def publish(self, push_message):
        """Sends a single push notification

        Args:
            push_message: A single PushMessage object.

        Returns:
           A PushTicket object which contains the results.
        """
        return self.publish_multiple([push_message])[0]

    def publish_multiple(self, push_messages):
        """Sends multiple push notifications at once

        Args:
            push_messages: An array of PushMessage objects.

        Returns:
           An array of PushTicket objects which contains the results.
        """
        push_tickets = []
        for start in itertools.count(0, self.max_message_count):
            chunk = list(
                itertools.islice(push_messages, start,
                                 start + self.max_message_count))
            if not chunk:
                break
            push_tickets.extend(self._publish_internal(chunk))
        return push_tickets

    def check_receipts_multiple(self, push_tickets):
        """
        Check receipts in batches of 1000 as per expo docs
        """
        receipts = []
        for start in itertools.count(0, self.max_receipt_count):
            chunk = list(
                itertools.islice(push_tickets, start,
                                 start + self.max_receipt_count))
            if not chunk:
                break
            receipts.extend(self._check_receipts_internal(chunk))
        return receipts

    def _check_receipts_internal(self, push_tickets):
        """
        Helper function for check_receipts_multiple
        """
        response = self.session.post(
            self.host + self.api_url + '/push/getReceipts',
            json={'ids': [push_ticket.id for push_ticket in push_tickets]},
            timeout=self.timeout)

        receipts = self.validate_and_get_receipts(response)
        return receipts

    def check_receipts(self, push_tickets):
        """  Checks the push receipts of the given push tickets """
        # Delayed import because this file is immediately read on install, and
        # the requests library may not be installed yet.
        response = requests.post(
            self.host + self.api_url + '/push/getReceipts',
            data=json.dumps(
                {'ids': [push_ticket.id for push_ticket in push_tickets]}),
            headers={
                'accept': 'application/json',
                'accept-encoding': 'gzip, deflate',
                'content-type': 'application/json',
            },
            timeout=self.timeout)
        receipts = self.validate_and_get_receipts(response)
        return receipts

    def validate_and_get_receipts(self, response):
        """
        Validate and get receipts for requests
        """
        # Let's validate the response format first.
        try:
            response_data = response.json()
        except ValueError:
            # The response isn't json. First, let's attempt to raise a normal
            # http error. If it's a 200, then we'll raise our own error.
            response.raise_for_status()
            raise PushServerError('Invalid server response', response)

        # If there are errors with the entire request, raise an error now.
        if 'errors' in response_data:
            raise PushServerError('Request failed',
                                  response,
                                  response_data=response_data,
                                  errors=response_data['errors'])

        # We expect the response to have a 'data' field with the responses.
        if 'data' not in response_data:
            raise PushServerError('Invalid server response',
                                  response,
                                  response_data=response_data)

        # Use the requests library's built-in exceptions for any remaining 4xx
        # and 5xx errors.
        response.raise_for_status()

        # At this point, we know it's a 200 and the response format is correct.
        # Now let's parse the responses per push notification.
        response_data = response_data['data']
        ret = []
        for r_id, val in response_data.items():
            ret.append(
                PushTicket(push_message=PushMessage(),
                           status=val.get('status', PushTicket.ERROR_STATUS),
                           message=val.get('message', ''),
                           details=val.get('details', None),
                           id=r_id))
        return ret
