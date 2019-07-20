# Copyright 2017 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Firebase user management sub module."""

import json

import requests
import six
from six.moves import urllib

from firebase_admin import _auth_utils
from firebase_admin import _user_import


USER_IMPORT_ERROR = 'USER_IMPORT_ERROR'
USER_DOWNLOAD_ERROR = 'LIST_USERS_ERROR'

MAX_LIST_USERS_RESULTS = 1000
MAX_IMPORT_USERS_SIZE = 1000


class Sentinel(object):

    def __init__(self, description):
        self.description = description


# Use this internally, until sentinels are available in the public API.
_UNSPECIFIED = Sentinel('No value specified')


DELETE_ATTRIBUTE = Sentinel('Value used to delete an attribute from a user profile')


class ApiCallError(Exception):
    """Represents an Exception encountered while invoking the Firebase user management API."""

    def __init__(self, code, message, error=None):
        Exception.__init__(self, message)
        self.code = code
        self.detail = error


class UserMetadata(object):
    """Contains additional metadata associated with a user account."""

    def __init__(self, creation_timestamp=None, last_sign_in_timestamp=None):
        self._creation_timestamp = _auth_utils.validate_timestamp(
            creation_timestamp, 'creation_timestamp')
        self._last_sign_in_timestamp = _auth_utils.validate_timestamp(
            last_sign_in_timestamp, 'last_sign_in_timestamp')

    @property
    def creation_timestamp(self):
        """ Creation timestamp in milliseconds since the epoch.

        Returns:
          integer: The user creation timestamp in milliseconds since the epoch.
        """
        return self._creation_timestamp

    @property
    def last_sign_in_timestamp(self):
        """ Last sign in timestamp in milliseconds since the epoch.

        Returns:
          integer: The last sign in timestamp in milliseconds since the epoch.
        """
        return self._last_sign_in_timestamp


class UserInfo(object):
    """A collection of standard profile information for a user.

    Used to expose profile information returned by an identity provider.
    """

    @property
    def uid(self):
        """Returns the user ID of this user."""
        raise NotImplementedError

    @property
    def display_name(self):
        """Returns the display name of this user."""
        raise NotImplementedError

    @property
    def email(self):
        """Returns the email address associated with this user."""
        raise NotImplementedError

    @property
    def phone_number(self):
        """Returns the phone number associated with this user."""
        raise NotImplementedError

    @property
    def photo_url(self):
        """Returns the photo URL of this user."""
        raise NotImplementedError

    @property
    def provider_id(self):
        """Returns the ID of the identity provider.

        This can be a short domain name (e.g. google.com), or the identity of an OpenID
        identity provider.
        """
        raise NotImplementedError


class UserRecord(UserInfo):
    """Contains metadata associated with a Firebase user account."""

    def __init__(self, data):
        super(UserRecord, self).__init__()
        if not isinstance(data, dict):
            raise ValueError('Invalid data argument: {0}. Must be a dictionary.'.format(data))
        if not data.get('localId'):
            raise ValueError('User ID must not be None or empty.')
        self._data = data

    @property
    def uid(self):
        """Returns the user ID of this user.

        Returns:
          string: A user ID string. This value is never None or empty.
        """
        return self._data.get('localId')

    @property
    def display_name(self):
        """Returns the display name of this user.

        Returns:
          string: A display name string or None.
        """
        return self._data.get('displayName')

    @property
    def email(self):
        """Returns the email address associated with this user.

        Returns:
          string: An email address string or None.
        """
        return self._data.get('email')

    @property
    def phone_number(self):
        """Returns the phone number associated with this user.

        Returns:
          string: A phone number string or None.
        """
        return self._data.get('phoneNumber')

    @property
    def photo_url(self):
        """Returns the photo URL of this user.

        Returns:
          string: A URL string or None.
        """
        return self._data.get('photoUrl')

    @property
    def provider_id(self):
        """Returns the provider ID of this user.

        Returns:
          string: A constant provider ID value.
        """
        return 'firebase'

    @property
    def email_verified(self):
        """Returns whether the email address of this user has been verified.

        Returns:
          bool: True if the email has been verified, and False otherwise.
        """
        return bool(self._data.get('emailVerified'))

    @property
    def disabled(self):
        """Returns whether this user account is disabled.

        Returns:
          bool: True if the user account is disabled, and False otherwise.
        """
        return bool(self._data.get('disabled'))

    @property
    def tokens_valid_after_timestamp(self):
        """Returns the time, in milliseconds since the epoch, before which tokens are invalid.

        Note: this is truncated to 1 second accuracy.

        Returns:
            int: Timestamp in milliseconds since the epoch, truncated to the second.
                 All tokens issued before that time are considered revoked.
        """
        valid_since = self._data.get('validSince')
        if valid_since is not None:
            return 1000 * int(valid_since)
        return 0

    @property
    def user_metadata(self):
        """Returns additional metadata associated with this user.

        Returns:
          UserMetadata: A UserMetadata instance. Does not return None.
        """
        def _int_or_none(key):
            if key in self._data:
                return int(self._data[key])
            return None
        return UserMetadata(_int_or_none('createdAt'), _int_or_none('lastLoginAt'))

    @property
    def provider_data(self):
        """Returns a list of UserInfo instances.

        Each object represents an identity from an identity provider that is linked to this user.

        Returns:
          list: A list of UserInfo objects, which may be empty.
        """
        providers = self._data.get('providerUserInfo', [])
        return [ProviderUserInfo(entry) for entry in providers]

    @property
    def custom_claims(self):
        """Returns any custom claims set on this user account.

        Returns:
          dict: A dictionary of claims or None.
        """
        claims = self._data.get('customAttributes')
        if claims:
            parsed = json.loads(claims)
            if parsed != {}:
                return parsed
        return None


class ExportedUserRecord(UserRecord):
    """Contains metadata associated with a user including password hash and salt."""

    def __init__(self, data):
        super(ExportedUserRecord, self).__init__(data)

    @property
    def password_hash(self):
        """The user's password hash as a base64-encoded string.

        If the Firebase Auth hashing algorithm (SCRYPT) was used to create the user account, this
        is the base64-encoded password hash of the user. If a different hashing algorithm was
        used to create this user, as is typical when migrating from another Auth system, this
        is an empty string. If no password is set, this is ``None``.
        """
        return self._data.get('passwordHash')

    @property
    def password_salt(self):
        """The user's password salt as a base64-encoded string.

        If the Firebase Auth hashing algorithm (SCRYPT) was used to create the user account, this
        is the base64-encoded password salt of the user. If a different hashing algorithm was
        used to create this user, as is typical when migrating from another Auth system, this is
        an empty string. If no password is set, this is ``None``.
        """
        return self._data.get('salt')


class ListUsersPage(object):
    """Represents a page of user records exported from a Firebase project.

    Provides methods for traversing the user accounts included in this page, as well as retrieving
    subsequent pages of users. The iterator returned by ``iterate_all()`` can be used to iterate
    through all users in the Firebase project starting from this page.
    """

    def __init__(self, download, page_token, max_results):
        self._download = download
        self._max_results = max_results
        self._current = download(page_token, max_results)

    @property
    def users(self):
        """A list of ``ExportedUserRecord`` instances available in this page."""
        return [ExportedUserRecord(user) for user in self._current.get('users', [])]

    @property
    def next_page_token(self):
        """Page token string for the next page (empty string indicates no more pages)."""
        return self._current.get('nextPageToken', '')

    @property
    def has_next_page(self):
        """A boolean indicating whether more pages are available."""
        return bool(self.next_page_token)

    def get_next_page(self):
        """Retrieves the next page of user accounts, if available.

        Returns:
            ListUsersPage: Next page of users, or None if this is the last page.
        """
        if self.has_next_page:
            return ListUsersPage(self._download, self.next_page_token, self._max_results)
        return None

    def iterate_all(self):
        """Retrieves an iterator for user accounts.

        Returned iterator will iterate through all the user accounts in the Firebase project
        starting from this page. The iterator will never buffer more than one page of users
        in memory at a time.

        Returns:
            iterator: An iterator of ExportedUserRecord instances.
        """
        return _UserIterator(self)


class ProviderUserInfo(UserInfo):
    """Contains metadata regarding how a user is known by a particular identity provider."""

    def __init__(self, data):
        super(ProviderUserInfo, self).__init__()
        if not isinstance(data, dict):
            raise ValueError('Invalid data argument: {0}. Must be a dictionary.'.format(data))
        if not data.get('rawId'):
            raise ValueError('User ID must not be None or empty.')
        self._data = data

    @property
    def uid(self):
        return self._data.get('rawId')

    @property
    def display_name(self):
        return self._data.get('displayName')

    @property
    def email(self):
        return self._data.get('email')

    @property
    def phone_number(self):
        return self._data.get('phoneNumber')

    @property
    def photo_url(self):
        return self._data.get('photoUrl')

    @property
    def provider_id(self):
        return self._data.get('providerId')


class ActionCodeSettings(object):
    """Contains required continue/state URL with optional Android and iOS settings.
    Used when invoking the email action link generation APIs.
    """

    def __init__(self, url, handle_code_in_app=None, dynamic_link_domain=None, ios_bundle_id=None,
                 android_package_name=None, android_install_app=None, android_minimum_version=None):
        self.url = url
        self.handle_code_in_app = handle_code_in_app
        self.dynamic_link_domain = dynamic_link_domain
        self.ios_bundle_id = ios_bundle_id
        self.android_package_name = android_package_name
        self.android_install_app = android_install_app
        self.android_minimum_version = android_minimum_version


def encode_action_code_settings(settings):
    """ Validates the provided action code settings for email link generation and
    populates the REST api parameters.

    settings - ``ActionCodeSettings`` object provided to be encoded
    returns  - dict of parameters to be passed for link gereration.
    """

    parameters = {}
    # url
    if not settings.url:
        raise ValueError("Dynamic action links url is mandatory")

    try:
        parsed = urllib.parse.urlparse(settings.url)
        if not parsed.netloc:
            raise ValueError('Malformed dynamic action links url: "{0}".'.format(settings.url))
        parameters['continueUrl'] = settings.url
    except Exception:
        raise ValueError('Malformed dynamic action links url: "{0}".'.format(settings.url))

    # handle_code_in_app
    if settings.handle_code_in_app is not None:
        if not isinstance(settings.handle_code_in_app, bool):
            raise ValueError('Invalid value provided for handle_code_in_app: {0}'
                             .format(settings.handle_code_in_app))
        parameters['canHandleCodeInApp'] = settings.handle_code_in_app

    # dynamic_link_domain
    if settings.dynamic_link_domain is not None:
        if not isinstance(settings.dynamic_link_domain, six.string_types):
            raise ValueError('Invalid value provided for dynamic_link_domain: {0}'
                             .format(settings.dynamic_link_domain))
        parameters['dynamicLinkDomain'] = settings.dynamic_link_domain

    # ios_bundle_id
    if settings.ios_bundle_id is not None:
        if not isinstance(settings.ios_bundle_id, six.string_types):
            raise ValueError('Invalid value provided for ios_bundle_id: {0}'
                             .format(settings.ios_bundle_id))
        parameters['iosBundleId'] = settings.ios_bundle_id

    # android_* attributes
    if (settings.android_minimum_version or settings.android_install_app) \
        and not settings.android_package_name:
        raise ValueError("Android package name is required when specifying other Android settings")

    if settings.android_package_name is not None:
        if not isinstance(settings.android_package_name, six.string_types):
            raise ValueError('Invalid value provided for android_package_name: {0}'
                             .format(settings.android_package_name))
        parameters['androidPackageName'] = settings.android_package_name

    if settings.android_minimum_version is not None:
        if not isinstance(settings.android_minimum_version, six.string_types):
            raise ValueError('Invalid value provided for android_minimum_version: {0}'
                             .format(settings.android_minimum_version))
        parameters['androidMinimumVersion'] = settings.android_minimum_version

    if settings.android_install_app is not None:
        if not isinstance(settings.android_install_app, bool):
            raise ValueError('Invalid value provided for android_install_app: {0}'
                             .format(settings.android_install_app))
        parameters['androidInstallApp'] = settings.android_install_app

    return parameters


class UserManager(object):
    """Provides methods for interacting with the Google Identity Toolkit."""

    def __init__(self, client):
        self._client = client

    def get_user(self, **kwargs):
        """Gets the user data corresponding to the provided key."""
        if 'uid' in kwargs:
            key, key_type = kwargs.pop('uid'), 'user ID'
            payload = {'localId' : [_auth_utils.validate_uid(key, required=True)]}
        elif 'email' in kwargs:
            key, key_type = kwargs.pop('email'), 'email'
            payload = {'email' : [_auth_utils.validate_email(key, required=True)]}
        elif 'phone_number' in kwargs:
            key, key_type = kwargs.pop('phone_number'), 'phone number'
            payload = {'phoneNumber' : [_auth_utils.validate_phone(key, required=True)]}
        else:
            raise TypeError('Unsupported keyword arguments: {0}.'.format(kwargs))

        try:
            body, http_resp = self._client.body_and_response(
                'post', '/accounts:lookup', json=payload)
        except requests.exceptions.RequestException as error:
            raise _auth_utils.handle_auth_backend_error(error)
        else:
            if not body or not body.get('users'):
                raise _auth_utils.UserNotFoundError(
                    'No user record found for the provided {0}: {1}.'.format(key_type, key),
                    http_response=http_resp)
            return body['users'][0]

    def list_users(self, page_token=None, max_results=MAX_LIST_USERS_RESULTS):
        """Retrieves a batch of users."""
        if page_token is not None:
            if not isinstance(page_token, six.string_types) or not page_token:
                raise ValueError('Page token must be a non-empty string.')
        if not isinstance(max_results, int):
            raise ValueError('Max results must be an integer.')
        elif max_results < 1 or max_results > MAX_LIST_USERS_RESULTS:
            raise ValueError(
                'Max results must be a positive integer less than '
                '{0}.'.format(MAX_LIST_USERS_RESULTS))

        payload = {'maxResults': max_results}
        if page_token:
            payload['nextPageToken'] = page_token
        try:
            return self._client.body('get', '/accounts:batchGet', params=payload)
        except requests.exceptions.RequestException as error:
            self._handle_http_error(USER_DOWNLOAD_ERROR, 'Failed to download user accounts.', error)

    def create_user(self, uid=None, display_name=None, email=None, phone_number=None,
                    photo_url=None, password=None, disabled=None, email_verified=None):
        """Creates a new user account with the specified properties."""
        payload = {
            'localId': _auth_utils.validate_uid(uid),
            'displayName': _auth_utils.validate_display_name(display_name),
            'email': _auth_utils.validate_email(email),
            'phoneNumber': _auth_utils.validate_phone(phone_number),
            'photoUrl': _auth_utils.validate_photo_url(photo_url),
            'password': _auth_utils.validate_password(password),
            'emailVerified': bool(email_verified) if email_verified is not None else None,
            'disabled': bool(disabled) if disabled is not None else None,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        try:
            body, http_resp = self._client.body_and_response('post', '/accounts', json=payload)
        except requests.exceptions.RequestException as error:
            raise _auth_utils.handle_auth_backend_error(error)
        else:
            if not body or not body.get('localId'):
                raise _auth_utils.UnexpectedResponseError(
                    'Failed to create new user.', http_response=http_resp)
            return body.get('localId')

    def update_user(self, uid, display_name=_UNSPECIFIED, email=None, phone_number=_UNSPECIFIED,
                    photo_url=_UNSPECIFIED, password=None, disabled=None, email_verified=None,
                    valid_since=None, custom_claims=_UNSPECIFIED):
        """Updates an existing user account with the specified properties"""
        payload = {
            'localId': _auth_utils.validate_uid(uid, required=True),
            'email': _auth_utils.validate_email(email),
            'password': _auth_utils.validate_password(password),
            'validSince': _auth_utils.validate_timestamp(valid_since, 'valid_since'),
            'emailVerified': bool(email_verified) if email_verified is not None else None,
            'disableUser': bool(disabled) if disabled is not None else None,
        }

        remove = []
        if display_name is not _UNSPECIFIED:
            if display_name is None or display_name is DELETE_ATTRIBUTE:
                remove.append('DISPLAY_NAME')
            else:
                payload['displayName'] = _auth_utils.validate_display_name(display_name)
        if photo_url is not _UNSPECIFIED:
            if photo_url is None or photo_url is DELETE_ATTRIBUTE:
                remove.append('PHOTO_URL')
            else:
                payload['photoUrl'] = _auth_utils.validate_photo_url(photo_url)
        if remove:
            payload['deleteAttribute'] = remove

        if phone_number is not _UNSPECIFIED:
            if phone_number is None or phone_number is DELETE_ATTRIBUTE:
                payload['deleteProvider'] = ['phone']
            else:
                payload['phoneNumber'] = _auth_utils.validate_phone(phone_number)

        if custom_claims is not _UNSPECIFIED:
            if custom_claims is None or custom_claims is DELETE_ATTRIBUTE:
                custom_claims = {}
            json_claims = json.dumps(custom_claims) if isinstance(
                custom_claims, dict) else custom_claims
            payload['customAttributes'] = _auth_utils.validate_custom_claims(json_claims)

        payload = {k: v for k, v in payload.items() if v is not None}
        try:
            body, http_resp = self._client.body_and_response(
                'post', '/accounts:update', json=payload)
        except requests.exceptions.RequestException as error:
            raise _auth_utils.handle_auth_backend_error(error)
        else:
            if not body or not body.get('localId'):
                raise _auth_utils.UnexpectedResponseError(
                    'Failed to update user: {0}.'.format(uid), http_response=http_resp)
            return body.get('localId')

    def delete_user(self, uid):
        """Deletes the user identified by the specified user ID."""
        _auth_utils.validate_uid(uid, required=True)
        try:
            body, http_resp = self._client.body_and_response(
                'post', '/accounts:delete', json={'localId' : uid})
        except requests.exceptions.RequestException as error:
            raise _auth_utils.handle_auth_backend_error(error)
        else:
            if not body or not body.get('kind'):
                raise _auth_utils.UnexpectedResponseError(
                    'Failed to delete user: {0}.'.format(uid), http_response=http_resp)

    def import_users(self, users, hash_alg=None):
        """Imports the given list of users to Firebase Auth."""
        try:
            if not users or len(users) > MAX_IMPORT_USERS_SIZE:
                raise ValueError(
                    'Users must be a non-empty list with no more than {0} elements.'.format(
                        MAX_IMPORT_USERS_SIZE))
            if any([not isinstance(u, _user_import.ImportUserRecord) for u in users]):
                raise ValueError('One or more user objects are invalid.')
        except TypeError:
            raise ValueError('users must be iterable')

        payload = {'users': [u.to_dict() for u in users]}
        if any(['passwordHash' in u for u in payload['users']]):
            if not isinstance(hash_alg, _user_import.UserImportHash):
                raise ValueError('A UserImportHash is required to import users with passwords.')
            payload.update(hash_alg.to_dict())
        try:
            response = self._client.body('post', '/accounts:batchCreate', json=payload)
        except requests.exceptions.RequestException as error:
            self._handle_http_error(USER_IMPORT_ERROR, 'Failed to import users.', error)
        else:
            if not isinstance(response, dict):
                raise ApiCallError(USER_IMPORT_ERROR, 'Failed to import users.')
            return response

    def generate_email_action_link(self, action_type, email, action_code_settings=None):
        """Fetches the email action links for types

        Args:
            action_type: String. Valid values ['VERIFY_EMAIL', 'EMAIL_SIGNIN', 'PASSWORD_RESET']
            email: Email of the user for which the action is performed
            action_code_settings: ``ActionCodeSettings`` object or dict (optional). Defines whether
                the link is to be handled by a mobile app and the additional state information to be
                passed in the deep link, etc.
        Returns:
            link_url: action url to be emailed to the user

        Raises:
            ApiCallError: If an error occurs while generating the link
            ValueError: If the provided arguments are invalid
        """
        payload = {
            'requestType': _auth_utils.validate_action_type(action_type),
            'email': _auth_utils.validate_email(email),
            'returnOobLink': True
        }

        if action_code_settings:
            payload.update(encode_action_code_settings(action_code_settings))

        try:
            body, http_resp = self._client.body_and_response(
                'post', '/accounts:sendOobCode', json=payload)
        except requests.exceptions.RequestException as error:
            raise _auth_utils.handle_auth_backend_error(error)
        else:
            if not body or not body.get('oobLink'):
                raise _auth_utils.UnexpectedResponseError(
                    'Failed to generate email action link.', http_response=http_resp)
            return body.get('oobLink')

    def _handle_http_error(self, code, msg, error):
        if error.response is not None:
            msg += '\nServer response: {0}'.format(error.response.content.decode())
        else:
            msg += '\nReason: {0}'.format(error)
        raise ApiCallError(code, msg, error)


class _UserIterator(object):
    """An iterator that allows iterating over user accounts, one at a time.

    This implementation loads a page of users into memory, and iterates on them. When the whole
    page has been traversed, it loads another page. This class never keeps more than one page
    of entries in memory.
    """

    def __init__(self, current_page):
        if not current_page:
            raise ValueError('Current page must not be None.')
        self._current_page = current_page
        self._index = 0

    def next(self):
        if self._index == len(self._current_page.users):
            if self._current_page.has_next_page:
                self._current_page = self._current_page.get_next_page()
                self._index = 0
        if self._index < len(self._current_page.users):
            result = self._current_page.users[self._index]
            self._index += 1
            return result
        raise StopIteration

    def __next__(self):
        return self.next()

    def __iter__(self):
        return self
