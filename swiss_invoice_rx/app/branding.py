"""Tenant-specific logos in the persistent Home Assistant data volume.

PDF rendering prefers a dedicated invoice logo and uses the business app logo
when no invoice logo is configured. The public login logo remains separate.
"""
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.datastructures import UploadFile

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 16_000_000
ALLOWED_FORMATS = {'PNG', 'JPEG', 'WEBP'}


def uploaded_logo(upload):
    """Return a decoded PNG in memory, or None when no file is selected."""
    if upload is None or not getattr(upload, 'filename', ''):
        return None
    if not isinstance(upload, UploadFile):
        raise ValueError('Bitte eine gueltige Bilddatei waehlen.')
    handle = upload.file
    handle.seek(0, 2)
    size = handle.tell()
    handle.seek(0)
    if not 0 < size <= MAX_BYTES:
        raise ValueError('Logo-Datei muss kleiner als 5 MB sein.')
    try:
        with Image.open(handle) as original:
            if original.format not in ALLOWED_FORMATS:
                raise ValueError('Nur PNG, JPG und WEBP sind erlaubt.')
            if original.width * original.height > MAX_PIXELS:
                raise ValueError('Logo-Aufloesung ist zu hoch.')
            original.verify()
        handle.seek(0)
        with Image.open(handle) as original:
            normalized = ImageOps.exif_transpose(original)
            normalized.thumbnail((1600, 900))
            normalized = normalized.convert('RGBA')
            from io import BytesIO
            out = BytesIO()
            normalized.save(out, format='PNG', optimize=True)
            return out.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('Die Logo-Datei ist kein gueltiges PNG/JPG/WEBP-Bild.') from exc


def save_company_logo(root, company_id, image_bytes):
    base = Path(root) / 'uploads' / str(int(company_id))
    base.mkdir(parents=True, exist_ok=True)
    name = 'app-logo-' + uuid4().hex + '.png'
    path = base / name
    path.write_bytes(image_bytes)
    return str(path.relative_to(root))


def save_site_logo(root, image_bytes):
    base = Path(root) / 'uploads' / 'site'
    base.mkdir(parents=True, exist_ok=True)
    target = base / 'login-logo.png'
    tmp = base / ('.tmp-' + uuid4().hex + '.png')
    try:
        tmp.write_bytes(image_bytes)
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return target


def site_logo_path(root):
    path = Path(root) / 'uploads' / 'site' / 'login-logo.png'
    base = (Path(root) / 'uploads' / 'site').resolve()
    return path if not path.is_symlink() and path.resolve().is_relative_to(base) and path.is_file() else None


def company_logo_path(root, company):
    if not company:
        return None
    base = (Path(root) / 'uploads' / str(int(company['id']))).resolve()
    for field in ('app_logo_path', 'logo_path'):
        relative = company.get(field, '')
        if not relative:
            continue
        path = (Path(root) / relative).resolve()
        if path.is_relative_to(base) and path.is_file() and path.suffix.lower() in ('.png', '.jpg', '.jpeg'):
            return path
    return None


def document_logo_path(root, company):
    """Resolve the invoice logo, falling back to this business's application logo.

    Paths from company records must stay in that company's uploads directory.
    No image from another tenant, absolute path or symlink is served.
    """
    if not company:
        return None
    try:
        cid = int(company['id'])
    except (KeyError, TypeError, ValueError):
        return None
    base = (Path(root) / 'uploads' / str(cid)).resolve()
    for field in ('logo_path', 'app_logo_path'):
        relative = company.get(field, '')
        if not relative or not isinstance(relative, str):
            continue
        relative_path = Path(relative)
        if relative_path.is_absolute():
            continue
        original = Path(root) / relative_path
        if original.is_symlink():
            continue
        path = original.resolve()
        if path.is_relative_to(base) and path.is_file() and path.suffix.lower() in ('.png', '.jpg', '.jpeg'):
            return path
    return None
