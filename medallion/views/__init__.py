from functools import wraps
import re

from flask import Response, request

from medallion.auth_service import AuthService

from .. import APPLICATION_INSTANCE, MEDIA_TYPE_TAXII_V21, auth
from ..exceptions import ProcessingError


def validate_version_parameter_in_accept_header():
    """All endpoints need to check the Accept Header for the correct Media Type"""
    accept_header = request.headers.get("accept", "").replace(" ", "").split(",")
    found = False

    for item in accept_header:
        result = re.match(r"^application/taxii\+json(;version=(\d\.\d))?$", item)
        if result:
            if len(result.groups()) >= 1:
                version_str = result.group(2)
                if version_str != "2.1":  # The server only supports 2.1
                    raise ProcessingError("The server does not support version {}".format(version_str), 406)
            found = True
            break

    if found is False:
        raise ProcessingError("Media type in the Accept header is invalid or not found", 406)


def validate_user_permission_on_collection(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_service = AuthService(request, auth.current_user())

        if not auth_service.can_user_access_collection():
            return Response(
                response="Unauthorized Access",
                status=401,
                mimetype=MEDIA_TYPE_TAXII_V21,
            )

        return f(*args, **kwargs)

    return decorated_function


def admin_only_endpoint(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not AuthService.is_user_admin(auth.current_user()):
            return Response(
                response="Unauthorized Access",
                status=401,
                mimetype=MEDIA_TYPE_TAXII_V21,
            )

        return f(*args, **kwargs)

    return decorated_function


def available_with_auth_backend_only(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not hasattr(APPLICATION_INSTANCE, "auth_backend"):
            return Response(
                response="This endpoint is only available with the MongoDB authentication backend.",
                status=400,
                mimetype=MEDIA_TYPE_TAXII_V21,
            )

        return f(*args, **kwargs)

    return decorated_function
