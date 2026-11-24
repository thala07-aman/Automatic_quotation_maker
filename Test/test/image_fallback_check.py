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
        import random
        rnd = random.Random(seed)
        d = ImageDraw.Draw(img)
        for _ in range(60):     # distinct random blocks per seed, so different "photos" really differ
            x, y = rnd.randrange(size[0]), rnd.randrange(size[1])
            d.rectangle([x, y, x + rnd.randrange(30, 200), y + rnd.randrange(30, 200)],
                        fill=(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
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


def fake_get_real_image(city, landmark=None, must=False):
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
assert len(calls) <= 10, len(calls)
print("lookups bounded OK ->", len(calls), "calls")

# h) the same picture is never used twice in a PDF, across cities and under different names
#    (Madurai / Rameshwaram bug: same photo or same-named place used again)
shared = jpeg(seed=11)
resized = f.resize_image_for_pdf(shared, 500, 400)          # same picture, different size / compression
photos.clear()
photos.update({
    "meenakshi temple": shared, "pamban bridge": jpeg(seed=12), "ramanathaswamy temple": resized,
    "dhanushkodi": jpeg(seed=13), "madurai": jpeg(seed=14), "rameshwaram": jpeg(seed=15),
    "city palace": jpeg(seed=16),
})
used = f.new_image_tracker()
r1 = f.fetch_day_images_from_landmarks("Madurai", ["Meenakshi Temple"], [], used)
r2 = f.fetch_day_images_from_landmarks("Rameshwaram", ["Ramanathaswamy Temple", "Dhanushkodi"], [], used)
assert r1["landmark1_name"] == "Meenakshi Temple"
assert "Ramanathaswamy Temple" not in [r2.get("landmark1_name"), r2.get("landmark2_name")], r2
assert r2["landmark1_name"] == "Dhanushkodi", r2
# the same place name on a later day / another city is not shown again either
r3 = f.fetch_day_images_from_landmarks("Madurai", ["Meenakshi Temple", "Madurai"], [], used)
assert r3 == {}, r3         # both were already shown in this PDF: better no photo than a repeat
# but another city's place with the same name is a different place
r4 = f.fetch_day_images_from_landmarks("Jaipur", ["City Palace"], [], used)
assert r4["landmark1_name"] == "City Palace", r4
print("no photo repeated in a PDF (exact copy, resized copy, same place) OK")

# g) placeholders are never returned by the picker; legacy function still can
assert f.fetch_destination_image("Agra", "Zzqx") is not None
print("legacy fetch_destination_image still returns bytes OK")
print("ALL OK")
