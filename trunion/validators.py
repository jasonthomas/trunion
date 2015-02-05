# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# ***** END LICENSE BLOCK *****

from pyramid.httpexceptions import HTTPBadRequest, HTTPConflict

import re
import time

import crypto

from signing_clients.apps import ParsingError, Signature


# From https://github.com/mozilla/browserid/blob/dev/lib/sanitize.js
EMAIL_REGEX = re.compile("^[-\w.!#$%&'*+/=?\^`{|}~]+@[-a-z\d_]+(\.[-a-z\d_]+)+$",
                         re.I)
PROD_URL_REGEX = re.compile("^(https?|app):\/\/[-a-z\d_]+(\.[-a-z\d_]+)*(:\d+)?$",
                            re.I)

# TODO
#    Don't permit other than the required fields to be safe:
#      typ, nbf, iss, iat, detail, verify, product(url, storedata),
#      user(type, value)


def valid_receipt(request):
    try:
        receipt = request.json_body
    except ValueError:
        raise HTTPBadRequest('Invalid JSON')

    now = long(time.time())

    for key in ('detail', 'verify', 'user', 'product', 'iss', 'iat', 'nbf'):
        if key not in receipt:
            raise HTTPBadRequest('missing %s' % key)

    # Verify the time windows
    #
    # Note: these checks should really reflect a window of opportunity taking
    #       clock drift and processing queue length/times into account
    #
    # Also, if we aren't going to revoke then the checks against signing['exp']
    # should definitely include a window
    signing = crypto.KEYSTORE.cert_data
    if receipt['iss'] not in request.registry.settings['trunion.permitted_issuers']:
        raise HTTPConflict("Bad issuer: \"%s\"" % receipt['iss'])
    if receipt['nbf'] < signing['iat']:
        raise HTTPConflict("nbf(not before) of receipt < iat(issued at) of "
                           "signing cert")
    if receipt['nbf'] > signing['exp']:
        raise HTTPConflict("nbf(not before) of receipt > exp(expires at) of "
                           "signing cert")
    if receipt['iat'] < signing['iat']:
        raise HTTPConflict("iat(issued at) of receipt < iat(issued at) of "
                           "signing cert")
    if receipt['iat'] > signing['exp']:
        raise HTTPConflict("iat(issued at) of receipt > exp(expires at) of "
                           "signing cert")
    if receipt['iat'] > now:
        raise HTTPConflict("iat(issued at) of receipt in the future")

    try:
        valid_user(receipt['user'])
        valid_product(receipt['product'])
    except:
        raise


def valid_user(obj):
    if type(obj) != dict:
        raise HTTPBadRequest('Invalid user struct: not a dict')
    if 'type' not in obj:
        raise HTTPBadRequest('Invalid user struct: no type defined')
    if 'value' not in obj:
        raise HTTPBadRequest('Invalid user struct: invalid value')
    if obj['type'] not in ('email', 'directed-identifier'):
        raise HTTPBadRequest('Invalid user struct: unknown type')
    if obj['type'] == 'email' and not EMAIL_REGEX.match(obj['value']):
        raise HTTPBadRequest('Invalid user struct: invalid value')
    return True


def valid_product(obj):
    if type(obj) != dict:
        raise HTTPBadRequest('Invalid product struct: not a dict')
    if 'url' not in obj:
        raise HTTPBadRequest('Invalid product struct: no URL provided')
    if 'storedata' not in obj:
        raise HTTPBadRequest('Invalid product struct: no storedata')
    if not PROD_URL_REGEX.match(obj['url']):
        raise HTTPBadRequest("Invalid product struct: URL doesn't look like "
                             "http://, https:// or app://: \"%s\"" % obj['url'])
    if len(obj['storedata']) < 1:
        raise HTTPBadRequest('Invalid product struct: storedata appears to be '
                             'empty')
    return True


def valid_app(request):
    """
    Not much validating to do, really.  So much validation is done by the
    separate validation service that we rely pretty heavily on the client
    end of this request doing its job.
    """
    return True


def valid_addon(request):
    """
    Since the addon_id parameter could possibly be anything we can't do much
    to validate it.  At the moment a reasonable bounds check on length is
    about all I'm certain is acceptable.

    We can use the signing_clients signature parser to at least make sure the
    signature is nominally correctly formatted.
    """
    if 'addon_id' not in request.POST:
        raise HTTPBadRequest('missing addon identifier')

    if 'file' not in request.POST:
        raise HTTPBadRequest('no payload to sign')

    if len(request.POST['addon_id']) < 4:
        raise HTTPBadRequest('addon_id is very short(<4 bytes): "%s"'
                             % request.POST['addon_id'])

    if len(request.POST['addon_id']) > 128:
        raise HTTPBadRequest('addon_id is very long(>128 bytes): "%s"'
                             % request.POST['addon_id'])

    try:
        s = Signature.parse(request.POST['file'].file.read())
    except ParsingError, e:
        raise HTTPBadRequest('Provided XPI signature file does not parse: '
                             '"%s"' % e)

    return True
