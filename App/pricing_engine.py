import pandas as pd

def load_pricing_data(uploaded_file):
    try:
        xls = pd.ExcelFile(uploaded_file)
        sheet_names = xls.sheet_names

        if "Hotels" not in sheet_names or "CarRental" not in sheet_names:
            return None, None

        hotels_df = pd.read_excel(xls, sheet_name="Hotels")
        car_df = pd.read_excel(xls, sheet_name="CarRental")

        print(pd.ExcelFile(uploaded_file).sheet_names)
        return hotels_df, car_df
    except Exception as e:
        return None, None

def get_hotel_price(hotels_df, city, star):
    df = hotels_df[
        (hotels_df["City"].str.lower() == city.lower()) &
        (hotels_df["Star"] == star)
    ]
    if df.empty:
        return None
    return df.iloc[0]["Price_Per_Night_Per_Person"], df.iloc[0]["Hotel_Name"]


def get_car_options(car_df):
    car_df = car_df.copy()
    car_df.columns = car_df.columns.str.strip().str.lower()

    required_cols = {"car_type", "price_per_day"}
    if not required_cols.issubset(set(car_df.columns)):
        raise ValueError(
            f"CarRental sheet must contain columns: {required_cols}. "
            f"Found: {car_df.columns.tolist()}"
        )

    options = {}
    for _, row in car_df.iterrows():
        options[row["car_type"]] = row["price_per_day"]

    return options


def get_hotel_options(hotels_df, city, preferred_star=None, limit=3):
    df = hotels_df[hotels_df["City"].str.lower() == city.lower()]

    if preferred_star:
        df = df[df["Star"] == preferred_star]

    if df.empty:
        return []

    # Sort by price (best value first)
    df = df.sort_values("Price_Per_Night_Per_Person")

    options = []
    for _, row in df.head(limit).iterrows():
        options.append({
            "hotel_name": row["Hotel_Name"],
            "star": row["Star"],
            "price": row["Price_Per_Night_Per_Person"],
            "image_url": row.get("Image_URL", "")
        })

    return options

