import pandas as pd

df = pd.read_csv("output/clubs_data.csv", low_memory=False)

# Keep only the columns William cares about
columns_to_keep = [
    "City",           # Column A
    "Club Name",      # Column D
    "Club Address",   # Column E
    "Accredited To",  # Column F
    "Team Numbers",   # Column H
    "Contact Name",   # Column I
    "Contact Phone",  # Column J
    "Contact Email",  # Column K
    "Contact Website", # Column L
    "ClubURL"
]
df = df[columns_to_keep]

# Filter: Keep rows where Club Name exists (not empty/NaN)
# AND Contact fields are not empty
mask = (
    df["Club Name"].notna() & (df["Club Name"].str.strip() != "")
)
# Contact fields that must be non-empty (Accredited To, Team Numbers, Contact Website can be empty/0)
contact_cols = ["Contact Name", "Contact Phone", "Contact Email"]
for col in contact_cols:
    mask = mask & df[col].notna() & (df[col].astype(str).str.strip() != "")

df = df[mask]

# Apply Title Case to Contact Name and Contact Phone
# Apply lowercase to Contact Email
df["Contact Name"] = df["Contact Name"].str.title()
df["Contact Email"] = df["Contact Email"].str.lower()

# Deduplicate based on Club Name + Contact Name + Contact Phone + Contact Email
# Ignoring differences in Club Address (Column E)
df.drop_duplicates(
    subset=["Club Name", "Contact Name", "Contact Phone", "Contact Email"],
    inplace=True
)

df.to_csv("new_club_data_test_pro_v3.csv", index=False)