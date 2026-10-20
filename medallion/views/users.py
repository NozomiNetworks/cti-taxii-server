import datetime
import logging

from flask import Blueprint, Response, current_app, json, request
from werkzeug.security import generate_password_hash

from . import (
    admin_only_endpoint, available_with_auth_backend_only,
    validate_version_parameter_in_accept_header
)
from .. import auth
from ..common import MEDIA_TYPE_TAXII_V21, datetime_to_string
from ..log import anonymize_user

users_bp = Blueprint("users", __name__)

# Module-level logger
log = logging.getLogger(__name__)

# Audit trail for user administration actions (RFC-001 §3.3); identities are
# anonymized per ADR-001.
audit_log = logging.getLogger("medallion.audit")
audit_log.setLevel(logging.INFO)


def _audit(action: str, target: str, outcome: int) -> None:
    audit_log.info(
        "audit %s", action,
        extra={
            "event": "audit",
            "action": action,
            "actor": anonymize_user(auth.current_user() or ""),
            "target": anonymize_user(target),
            "outcome": outcome,
        },
    )


@users_bp.route("/users/", methods=["GET", "POST"])
@auth.login_required
@admin_only_endpoint
@available_with_auth_backend_only
def get_add_users():
    """Custom endpoint to manage the users in the authentication backend (currently only MongoDB is supported)."""
    validate_version_parameter_in_accept_header()

    if request.method == "GET":
        return Response(
            response=json.dumps([
                current_app.auth_backend.format_user_response(user)
                for user in current_app.auth_backend.get_all_users()
            ]),
            status=200,
            mimetype=MEDIA_TYPE_TAXII_V21,
        )
    elif request.method == "POST":
        body = request.get_json()

        err = None
        status = 400

        if "_id" not in body:
            err = 'Missing required field "_id" in request body.'

        elif "password" not in body and "password_hash" not in body:
            err = 'Missing both "password" and "password_hash" in request body.'

        elif current_app.auth_backend.get_user_by_username(body["_id"]):
            err = f'User with _id "{body["_id"]}" already exists.'
            status = 409

        elif "password" in body and "password_hash" in body:
            err = 'Provide either "password" or "password_hash", not both.'

        if err:
            response = Response(
                response=json.dumps({"error": err}),
                status=status,
                mimetype=MEDIA_TYPE_TAXII_V21,
            )
            if status == 409:
                _audit("create_user", body["_id"], status)
            return response

        user_info = {
            "company_name": body.get("company_name", ""),
            "contact_name": body.get("contact_name", ""),
            "is_admin": body.get("is_admin", False),
            "license": body.get("license", "nozomi"),
            "created": datetime_to_string(datetime.datetime.now(datetime.UTC)),
            "_id": body["_id"],
            "password": get_db_password_from_request(body),
        }

        current_app.auth_backend.add_user(user_info)
        user = current_app.auth_backend.get_user_by_username(body["_id"])
        response = Response(
            response=json.dumps(current_app.auth_backend.format_user_response(user)),
            status=201,
            mimetype=MEDIA_TYPE_TAXII_V21,
        )
        _audit("create_user", body["_id"], 201)
        return response


@users_bp.route("/users/reset_password/", methods=["POST"])
@auth.login_required
@available_with_auth_backend_only
def reset_password():
    """Custom endpoint allowing the authenticated user to reset their own password.

    The target user is always the currently authenticated user, so a user can only ever change their own password.
    """
    validate_version_parameter_in_accept_header()

    body = request.get_json()

    if "password" not in body:
        return Response(
            response=json.dumps({"error": 'Missing "password" in request body.'}),
            status=400,
            mimetype=MEDIA_TYPE_TAXII_V21,
        )

    username = auth.current_user()
    log.info('User "%s" is resetting their password.', anonymize_user(username))

    current_app.auth_backend.update_user(username, {
        "updated": datetime_to_string(datetime.datetime.now(datetime.UTC)),
        "password": get_db_password_from_request(body),
    })
    user = current_app.auth_backend.get_user_by_username(username)

    return Response(
        response=json.dumps(current_app.auth_backend.format_user_response(user)),
        status=200,
        mimetype=MEDIA_TYPE_TAXII_V21,
    )


@users_bp.route("/users/<string:user_id>/", methods=["PUT", "DELETE"])
@auth.login_required
@admin_only_endpoint
@available_with_auth_backend_only
def delete_update_user(user_id):
    """Custom endpoint to update or delete an existing user in the authentication backend (currently only MongoDB is supported)."""
    validate_version_parameter_in_accept_header()

    if not current_app.auth_backend.get_user_by_username(user_id):
        return Response(
            response=json.dumps({"error": f'User with _id "{user_id}" does not exist.'}),
            status=404,
            mimetype=MEDIA_TYPE_TAXII_V21,
        )

    if request.method == "DELETE":
        current_app.auth_backend.delete_user(user_id)
        response = Response(
            status=204,
            mimetype=MEDIA_TYPE_TAXII_V21,
        )
        _audit("delete_user", user_id, 204)
        return response

    body = request.get_json()

    # Only update the fields that are explicitly provided in the request body, leaving any omitted field untouched.
    user_info = {
        field: body[field]
        for field in ("company_name", "contact_name", "is_admin", "license")
        if field in body
    }

    user_info["updated"] = datetime_to_string(datetime.datetime.now(datetime.UTC))

    current_app.auth_backend.update_user(user_id, user_info)
    user = current_app.auth_backend.get_user_by_username(user_id)
    response = Response(
        response=json.dumps(current_app.auth_backend.format_user_response(user)),
        status=200,
        mimetype=MEDIA_TYPE_TAXII_V21,
    )
    _audit("update_user", user_id, 200)
    return response


def get_db_password_from_request(body: dict) -> str:
    """Extract the password or password_hash from the request body.

    Args:
        body (dict): The request body.
    Returns:
        str: The password hash to store in the database.
    """
    if "password_hash" in body:
        return body["password_hash"]

    return generate_password_hash(body["password"])
