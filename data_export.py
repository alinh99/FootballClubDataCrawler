import pandas as pd

df = pd.read_csv("output/clubs_data.csv")
# df.dropna(how="all", inplace=True)
df.drop_duplicates(subset=["ClubId"], inplace=True)
df.drop(columns=["SearchId"], inplace=True, errors="ignore")
df.to_csv("new_club_data_test_pro.csv", index=False)
