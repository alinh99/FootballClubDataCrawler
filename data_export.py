import pandas as pd

df = pd.read_csv("output/clubs_data.csv", low_memory=False)
# df.dropna(how="all", inplace=True)
df.drop_duplicates(subset=["Club Name","Club Address","Accredited To","Football Types","Team Numbers","Contact Name","Contact Phone","Contact Email","Contact Website","WeekDays","Latitude","Longitude","SchoolYear","FootballType","DisabilityOption","SearchId","WgsClubId","GroundName","BookingVenue","BookingAddress"], inplace=True)
df.to_csv("new_club_data_test_pro.csv", index=False)

