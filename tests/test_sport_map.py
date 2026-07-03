from strava_komoot.komoot import STRAVA_TO_KOMOOT_SPORT, STRAVA_VIS_TO_KOMOOT


class TestSportMapping:
    def test_ride_to_touringbicycle(self):
        assert STRAVA_TO_KOMOOT_SPORT["Ride"] == "touringbicycle"

    def test_gravel_to_mtb_easy(self):
        assert STRAVA_TO_KOMOOT_SPORT["GravelRide"] == "mtb_easy"

    def test_mtb_to_mtb(self):
        assert STRAVA_TO_KOMOOT_SPORT["MountainBikeRide"] == "mtb"

    def test_ebike_to_e_touringbicycle(self):
        assert STRAVA_TO_KOMOOT_SPORT["EBikeRide"] == "e_touringbicycle"

    def test_unknown_sport_falls_back(self):
        from strava_komoot.komoot import KomootSink
        assert KomootSink.map_sport("Run") == "touringbicycle"


class TestVisibilityMapping:
    def test_everyone_to_friends(self):
        assert STRAVA_VIS_TO_KOMOOT["everyone"] == "friends"

    def test_followers_only_to_friends(self):
        assert STRAVA_VIS_TO_KOMOOT["followers_only"] == "friends"

    def test_only_me_to_private(self):
        assert STRAVA_VIS_TO_KOMOOT["only_me"] == "private"

    def test_none_falls_back_to_private(self):
        from strava_komoot.komoot import KomootSink
        assert KomootSink.map_visibility(None) == "private"

    def test_unknown_falls_back_to_private(self):
        from strava_komoot.komoot import KomootSink
        assert KomootSink.map_visibility("unknown") == "private"
