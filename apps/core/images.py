"""Image uploads: staff photos, staff ID documents, doctor and nurse photos.

Every upload is opened with Pillow, checked to be a real JPEG/PNG/WebP within size limits, turned upright,
resized and re-encoded as a fresh JPEG. Re-encoding drops EXIF (GPS position, camera serial) and anything
smuggled inside the file. The result is encrypted and stored in the database (StoredImage).
"""

import hashlib
import io
import warnings

from django.http import Http404, HttpResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.accounts.roles import has_role

from . import audit
from .crypto import decrypt_bytes, encrypt_bytes
from .models import StoredImage

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "MPO"}
LONGEST_SIDE = {"staff_photo": 512, "practitioner_photo": 512, "staff_id": 1600, "signature": 900}
MAX_PIXELS = 30_000_000  # ~ a 7,000 × 4,300 photo; larger is refused before decoding
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

# Who may see each kind. Staff photos: anyone signed in (shown in the top bar and staff lists).
VIEW_ROLES = {
    "staff_photo": None,
    "practitioner_photo": ("customer_care", "supervisor", "manager", "mcj_confirmer", "auditor"),
    "staff_id": ("ict_admin", "manager"),
    "signature": ("customer_care", "supervisor", "manager", "auditor"),
}


class ImageRejected(ValueError):
    """The upload is not an acceptable image."""


def store(upload, kind, *, user=None):
    """Validate, normalise and store an uploaded image; returns the StoredImage."""
    if kind not in LONGEST_SIDE:
        raise ValueError(kind)
    if upload is None:
        raise ImageRejected("Choose an image file.")
    if upload.size > MAX_UPLOAD_BYTES:
        raise ImageRejected("The image is larger than 8 MB.")
    raw = upload.read(MAX_UPLOAD_BYTES + 1)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(io.BytesIO(raw))  # reads the header only
            if probe.width * probe.height > MAX_PIXELS:
                raise ImageRejected("The image is too large (pixels). Use a photo under 30 megapixels.")
            probe.verify()
        img = Image.open(io.BytesIO(raw))
        if img.format not in ALLOWED_FORMATS:
            raise ImageRejected("Use a JPEG, PNG or WebP image.")
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            rgba = img.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        img = img.convert("RGB")
        img.thumbnail((LONGEST_SIDE[kind], LONGEST_SIDE[kind]), Image.Resampling.LANCZOS)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageRejected("The image is too large (pixels). Use a photo under 30 megapixels.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ImageRejected("That file is not a readable image.") from exc
    if min(img.size) < 64:
        raise ImageRejected("The image is too small — at least 64 pixels on each side.")
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85, optimize=True)
    data = out.getvalue()
    return StoredImage.objects.create(
        kind=kind,
        data=encrypt_bytes(data),
        width=img.width,
        height=img.height,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        created_by=user,
    )


def replace(old, upload, kind, *, user=None):
    """Store a new image and delete the one it replaces."""
    new = store(upload, kind, user=user)
    if old is not None:
        StoredImage.objects.filter(pk=old.pk).delete()
    return new


def can_view(user, kind):
    """Role check for one image kind."""
    roles = VIEW_ROLES.get(kind, ())
    return roles is None or has_role(user, *roles)


def serve(request, image):
    """Decrypted image bytes for an authorised viewer; ID documents are never cached and each view is audited."""
    if image is None or not can_view(request.user, image.kind):
        raise Http404
    resp = HttpResponse(decrypt_bytes(image.data), content_type=image.content_type)
    if image.kind == "staff_id":
        resp["Cache-Control"] = "no-store"
        audit.record("staff.id_viewed", image, f"Staff ID document viewed by {request.user.username}")
    else:
        resp["Cache-Control"] = "private, max-age=300"
    resp["Content-Disposition"] = "inline"
    return resp


def store_signature(data_url, *, user=None):
    """A signature drawn on the counter screen (a PNG data URL from the signature pad): stored like any other image."""
    import base64

    from django.core.files.uploadedfile import SimpleUploadedFile

    prefix = "data:image/png;base64,"
    if not data_url or not data_url.startswith(prefix):
        raise ImageRejected("No signature was drawn.")
    raw = base64.b64decode(data_url[len(prefix) :], validate=True)
    if len(raw) > 600_000:
        raise ImageRejected("The signature image is too large.")
    return store(SimpleUploadedFile("signature.png", raw, content_type="image/png"), "signature", user=user)
