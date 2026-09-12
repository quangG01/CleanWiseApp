from urllib.parse import urlparse


def extract_cloudinary_public_id(image_url):
    """
    Lấy public_id từ Cloudinary URL.

    Ví dụ:

    https://res.cloudinary.com/demo/image/upload/v123456/
    cleanwise/service_images/service_abc123.jpg

    => cleanwise/service_images/service_abc123
    """

    if not image_url:
        return None

    try:
        parsed = urlparse(image_url)

        path = parsed.path

        marker = "/image/upload/"

        if marker not in path:
            return None

        public_path = path.split(
            marker,
            1
        )[1]

        # ---------------------------------------------------------
        # Bỏ version của Cloudinary
        # Ví dụ:
        # v123456/cleanwise/service_images/xxx.jpg
        # ---------------------------------------------------------

        parts = public_path.split("/")

        if (
            parts
            and parts[0].startswith("v")
            and parts[0][1:].isdigit()
        ):
            parts = parts[1:]

        public_path = "/".join(parts)

        if not public_path:
            return None

        # ---------------------------------------------------------
        # Bỏ extension
        # xxx.jpg -> xxx
        # ---------------------------------------------------------

        public_id = public_path.rsplit(
            ".",
            1
        )[0]

        return public_id

    except Exception:
        return None
