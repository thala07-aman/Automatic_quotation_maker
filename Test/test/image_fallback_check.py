"""
Checks for the image fallback logic (no network needed).

Run from the project root:
    python3 Test/test/image_fallback_check.py
"""
import io
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "App"))
import image_fetcher as f  # noqa: E402


def jpeg(size=(800, 600), color=(120, 120, 120), noisy=True, seed=0):
    img = Image.new("RGB", size, color)
    if noisy:
        d = ImageDraw.Draw(img)
        for i in range(0, size[0], 20):
            d.rectangle([i, 0, i + 10 + seed % 7, size[1]], fill=((i * 3 + seed * 40) % 255, (i + seed * 70) % 255, 90))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


# ---------- is_usable_image ----------
assert f.is_usable_image(jpeg()), "normal photo should pass"
assert not f.is_usable_image(None), "None"
assert not f.is_usable_image(b""), "empty"
assert not f.is_usable_image(b"not an image"), "corrupt bytes"
assert not f.is_usable_image(jpeg(noisy=False)), "flat single-colour image (blank)"
assert not f.is_usable_image(jpeg(size=(200, 150))), "too small"
print("is_usable_image OK")

# ---------- substitution ----------
photos = {  # place -> image bytes, or None when "no photo can be found"
    "taj mahal": jpeg(seed=1),
    "agra fort": jpeg(seed=2),
    "mehtab bagh": None,           # the problem case
    "sikandra": jpeg(seed=3),
    "fatehpur sikri": jpeg(seed=4),
    "agra": jpeg(seed=5),          # city overview
}
calls = []


def fake_get_real_image(city, landmark=None):
    calls.append(landmark)
    return photos.get((landmark or city).strip().lower())


f.get_real_image = fake_get_real_image

# a) everything available: own landmarks used, no substitution
used = f.new_image_tracker()
r = f.fetch_day_images_from_landmarks("Agra", ["Taj Mahal", "Agra Fort"], ["Sikandra"], used)
assert [r["landmark1_name"], r["landmark2_name"]] == ["Taj Mahal", "Agra Fort"], r
print("own landmarks used when photos exist OK")

# b) one landmark has no photo: another place from the city replaces it
used = f.new_image_tracker()
r = f.fetch_day_images_from_landmarks("Agra", ["Taj Mahal", "Mehtab Bagh"], ["Sikandra", "Fatehpur Sikri"], used)
assert r["landmark1_name"] == "Taj Mahal" and r["landmark2_name"] == "Sikandra", r
assert "image1" in r and "image2" in r
print("missing landmark replaced by another place OK ->", r["landmark2_name"])

# c) substitute isn't reused on the next day
r2 = f.fetch_day_images_from_landmarks("Agra", ["Mehtab Bagh", "Agra Fort"], ["Sikandra", "Fatehpur Sikri"], used)
names = [r2["landmark1_name"], r2["landmark2_name"]]
assert "Sikandra" not in names and "Fatehpur Sikri" in names, names
print("substitute not repeated on later days OK ->", names)

# d) same photo under two names is not shown twice in one day
photos["duplicate spot"] = photos["taj mahal"]
used = f.new_image_tracker()
r = f.fetch_day_images_from_landmarks("Agra", ["Taj Mahal", "Duplicate Spot"], ["Sikandra"], used)
assert r["landmark2_name"] == "Sikandra", r
print("identical photo skipped OK")

# e) nothing at all found for alternates: falls back to city overview, then to fewer images (never blank)
for k in list(photos):
    if k not in ("taj mahal", "agra"):
        photos[k] = None
used = f.new_image_tracker()
r = f.fetch_day_images_from_landmarks("Agra", ["Mehtab Bagh", "Taj Mahal"], ["Sikandra"], used)
assert sorted([r["landmark1_name"], r["landmark2_name"]]) == ["Agra", "Taj Mahal"], r
photos["agra"] = None
used = f.new_image_tracker()
r = f.fetch_day_images_from_landmarks("Agra", ["Mehtab Bagh", "Sikandra"], [], used)
assert r == {}, r
print("city-overview fallback and empty result OK")

# f) bounded work: many failing alternates don't cause unbounded lookups
calls.clear()
used = f.new_image_tracker()
f.fetch_day_images_from_landmarks("Agra", ["Mehtab Bagh", "Sikandra"], [f"Nowhere {i}" for i in range(40)], used)
assert len(calls) <= 8, len(calls)
print("lookups bounded OK ->", len(calls), "calls")

# g) placeholders are never returned by the picker; legacy function still can
assert f.fetch_destination_image("Agra", "Zzqx") is not None
print("legacy fetch_destination_image still returns bytes OK")
print("ALL OK")
