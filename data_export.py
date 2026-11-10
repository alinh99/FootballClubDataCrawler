import pandas as pd

df = pd.read_csv("output/clubs_data.csv")
df.dropna(how="all", inplace=True)
df.drop_duplicates(subset=["Club Name", "ClubId", "Club Address","Accredited To","Football Types","Team Numbers","Contact Name","Contact Phone","Contact Email","Contact Website","WeekDays", "SchoolYear","FootballType","DisabilityOption","WgsClubId","ClubId","GroundName"], inplace=True)
df.to_csv("new_club_data_test_pro.csv", index=False)
