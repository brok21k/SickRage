# Author: Nic Wolfe <nic@wolfeden.ca>
# URL: http://code.google.com/p/sickbeard/
#
# This file is part of SickRage.
#
# SickRage is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# SickRage is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with SickRage.  If not, see <http://www.gnu.org/licenses/>.

import datetime

import sickbeard
import os.path

from sickbeard import db, common, helpers, logger

from sickbeard import encodingKludge as ek
from sickbeard.name_parser.parser import NameParser, InvalidNameException

MIN_DB_VERSION = 9  # oldest db version we support migrating from
MAX_DB_VERSION = 38

class MainSanityCheck(db.DBSanityCheck):
    def check(self):
        self.fix_missing_table_indexes()
        self.fix_duplicate_shows()
        self.fix_duplicate_episodes()
        self.fix_orphan_episodes()
        self.fix_unaired_episodes()

    def fix_duplicate_shows(self, column='indexer_id'):

        sqlResults = self.connection.select(
            "SELECT show_id, " + column + ", COUNT(" + column + ") as count FROM tv_shows GROUP BY " + column + " HAVING count > 1")

        for cur_duplicate in sqlResults:

            logger.log(u"Duplicate show detected! " + column + ": " + str(cur_duplicate[column]) + u" count: " + str(
                cur_duplicate["count"]), logger.DEBUG)

            cur_dupe_results = self.connection.select(
                "SELECT show_id, " + column + " FROM tv_shows WHERE " + column + " = ? LIMIT ?",
                [cur_duplicate[column], int(cur_duplicate["count"]) - 1]
            )

            for cur_dupe_id in cur_dupe_results:
                logger.log(
                    u"Deleting duplicate show with " + column + ": " + str(cur_dupe_id[column]) + u" show_id: " + str(
                        cur_dupe_id["show_id"]))
                self.connection.action("DELETE FROM tv_shows WHERE show_id = ?", [cur_dupe_id["show_id"]])

        else:
            logger.log(u"No duplicate show, check passed")

    def fix_duplicate_episodes(self):

        sqlResults = self.connection.select(
            "SELECT showid, season, episode, COUNT(showid) as count FROM tv_episodes GROUP BY showid, season, episode HAVING count > 1")

        for cur_duplicate in sqlResults:

            logger.log(u"Duplicate episode detected! showid: " + str(cur_duplicate["showid"]) + u" season: " + str(
                cur_duplicate["season"]) + u" episode: " + str(cur_duplicate["episode"]) + u" count: " + str(
                cur_duplicate["count"]), logger.DEBUG)

            cur_dupe_results = self.connection.select(
                "SELECT episode_id FROM tv_episodes WHERE showid = ? AND season = ? and episode = ? ORDER BY episode_id DESC LIMIT ?",
                [cur_duplicate["showid"], cur_duplicate["season"], cur_duplicate["episode"],
                 int(cur_duplicate["count"]) - 1]
            )

            for cur_dupe_id in cur_dupe_results:
                logger.log(u"Deleting duplicate episode with episode_id: " + str(cur_dupe_id["episode_id"]))
                self.connection.action("DELETE FROM tv_episodes WHERE episode_id = ?", [cur_dupe_id["episode_id"]])

        else:
            logger.log(u"No duplicate episode, check passed")

    def fix_orphan_episodes(self):

        sqlResults = self.connection.select(
            "SELECT episode_id, showid, tv_shows.indexer_id FROM tv_episodes LEFT JOIN tv_shows ON tv_episodes.showid=tv_shows.indexer_id WHERE tv_shows.indexer_id is NULL")

        for cur_orphan in sqlResults:
            logger.log(u"Orphan episode detected! episode_id: " + str(cur_orphan["episode_id"]) + " showid: " + str(
                cur_orphan["showid"]), logger.DEBUG)
            logger.log(u"Deleting orphan episode with episode_id: " + str(cur_orphan["episode_id"]))
            self.connection.action("DELETE FROM tv_episodes WHERE episode_id = ?", [cur_orphan["episode_id"]])

        else:
            logger.log(u"No orphan episodes, check passed")

    def fix_missing_table_indexes(self):
        if not self.connection.select("PRAGMA index_info('idx_indexer_id')"):
            logger.log(u"Missing idx_indexer_id for TV Shows table detected!, fixing...")
            self.connection.action("CREATE UNIQUE INDEX idx_indexer_id ON tv_shows (indexer_id);")

        if not self.connection.select("PRAGMA index_info('idx_tv_episodes_showid_airdate')"):
            logger.log(u"Missing idx_tv_episodes_showid_airdate for TV Episodes table detected!, fixing...")
            self.connection.action("CREATE INDEX idx_tv_episodes_showid_airdate ON tv_episodes(showid,airdate);")

        if not self.connection.select("PRAGMA index_info('idx_showid')"):
            logger.log(u"Missing idx_showid for TV Episodes table detected!, fixing...")
            self.connection.action("CREATE INDEX idx_showid ON tv_episodes (showid);")

        if not self.connection.select("PRAGMA index_info('idx_status')"):
            logger.log(u"Missing idx_status for TV Episodes table detected!, fixing...")
            self.connection.action("CREATE INDEX idx_status ON tv_episodes (status,season,episode,airdate)")

        if not self.connection.select("PRAGMA index_info('idx_sta_epi_air')"):
            logger.log(u"Missing idx_sta_epi_air for TV Episodes table detected!, fixing...")
            self.connection.action("CREATE INDEX idx_sta_epi_air ON tv_episodes (status,episode, airdate)")

        if not self.connection.select("PRAGMA index_info('idx_sta_epi_sta_air')"):
            logger.log(u"Missing idx_sta_epi_sta_air for TV Episodes table detected!, fixing...")
            self.connection.action("CREATE INDEX idx_sta_epi_sta_air ON tv_episodes (season,episode, status, airdate)")

    def fix_unaired_episodes(self):

        curDate = datetime.date.today()

        sqlResults = self.connection.select(
            "SELECT episode_id, showid FROM tv_episodes WHERE airdate > ? AND status in (?,?)",
            [curDate.toordinal(), common.SKIPPED, common.WANTED])

        for cur_unaired in sqlResults:
            logger.log(u"UNAIRED episode detected! episode_id: " + str(cur_unaired["episode_id"]) + " showid: " + str(
                cur_unaired["showid"]), logger.DEBUG)
            logger.log(u"Fixing unaired episode status with episode_id: " + str(cur_unaired["episode_id"]))
            self.connection.action("UPDATE tv_episodes SET status = ? WHERE episode_id = ?",
                                   [common.UNAIRED, cur_unaired["episode_id"]])

        else:
            logger.log(u"No UNAIRED episodes, check passed")


def backupDatabase(version):
    logger.log(u"Backing up database before upgrade")
    if not helpers.backupVersionedFile(db.dbFilename(), version):
        logger.log_error_and_exit(u"Database backup failed, abort upgrading database")
    else:
        logger.log(u"Proceeding with upgrade")


# ======================
# = Main DB Migrations =
# ======================
# Add new migrations at the bottom of the list; subclass the previous migration.

class InitialSchema(db.SchemaUpgrade):
    def test(self):
        return self.hasTable("db_version")

    def execute(self):
        if not self.hasTable("tv_shows") and not self.hasTable("db_version"):
            queries = [
                "CREATE TABLE db_version (db_version INTEGER);",
                "CREATE TABLE history (action NUMERIC, date NUMERIC, showid NUMERIC, season NUMERIC, episode NUMERIC, quality NUMERIC, resource TEXT, provider TEXT)",
                "CREATE TABLE imdb_info (indexer_id INTEGER PRIMARY KEY, imdb_id TEXT, title TEXT, year NUMERIC, akas TEXT, runtimes NUMERIC, genres TEXT, countries TEXT, country_codes TEXT, certificates TEXT, rating TEXT, votes INTEGER, last_update NUMERIC)",
                "CREATE TABLE info (last_backlog NUMERIC, last_indexer NUMERIC, last_proper_search NUMERIC)",
                "CREATE TABLE scene_numbering(indexer TEXT, indexer_id INTEGER, season INTEGER, episode INTEGER,scene_season INTEGER, scene_episode INTEGER, PRIMARY KEY(indexer_id, season, episode))",
                "CREATE TABLE tv_shows (show_id INTEGER PRIMARY KEY, indexer_id NUMERIC, indexer TEXT, show_name TEXT, location TEXT, network TEXT, genre TEXT, classification TEXT, runtime NUMERIC, quality NUMERIC, airs TEXT, status TEXT, flatten_folders NUMERIC, paused NUMERIC, startyear NUMERIC, air_by_date NUMERIC, lang TEXT, subtitles NUMERIC, notify_list TEXT, imdb_id TEXT, last_update_indexer NUMERIC, dvdorder NUMERIC, archive_firstmatch NUMERIC, rls_require_words TEXT, rls_ignore_words TEXT, sports NUMERIC);",
                "CREATE TABLE tv_episodes (episode_id INTEGER PRIMARY KEY, showid NUMERIC, indexerid NUMERIC, indexer TEXT, name TEXT, season NUMERIC, episode NUMERIC, description TEXT, airdate NUMERIC, hasnfo NUMERIC, hastbn NUMERIC, status NUMERIC, location TEXT, file_size NUMERIC, release_name TEXT, subtitles TEXT, subtitles_searchcount NUMERIC, subtitles_lastsearch TIMESTAMP, is_proper NUMERIC, scene_season NUMERIC, scene_episode NUMERIC);",
                "CREATE UNIQUE INDEX idx_indexer_id ON tv_shows (indexer_id)",
                "CREATE INDEX idx_showid ON tv_episodes (showid);",
                "CREATE INDEX idx_sta_epi_air ON tv_episodes (status,episode, airdate);",
                "CREATE INDEX idx_sta_epi_sta_air ON tv_episodes (season,episode, status, airdate);",
                "CREATE INDEX idx_status ON tv_episodes (status,season,episode,airdate);",
                "CREATE INDEX idx_tv_episodes_showid_airdate ON tv_episodes(showid,airdate)",
                "INSERT INTO db_version (db_version) VALUES (31);"
            ]
            for query in queries:
                self.connection.action(query)

        else:
            cur_db_version = self.checkDBVersion()

            if cur_db_version < MIN_DB_VERSION:
                logger.log_error_and_exit(u"Your database version (" + str(
                    cur_db_version) + ") is too old to migrate from what this version of SickRage supports (" + \
                                          str(MIN_DB_VERSION) + ").\n" + \
                                          "Upgrade using a previous version (tag) build 496 to build 501 of SickRage first or remove database file to begin fresh."
                )

            if cur_db_version > MAX_DB_VERSION:
                logger.log_error_and_exit(u"Your database version (" + str(
                    cur_db_version) + ") has been incremented past what this version of SickRage supports (" + \
                                          str(MAX_DB_VERSION) + ").\n" + \
                                          "If you have used other forks of SickRage, your database may be unusable due to their modifications."
                )


class AddSizeAndSceneNameFields(InitialSchema):
    def test(self):
        return self.checkDBVersion() >= 10

    def execute(self):

        backupDatabase(10)

        if not self.hasColumn("tv_episodes", "file_size"):
            self.addColumn("tv_episodes", "file_size")

        if not self.hasColumn("tv_episodes", "release_name"):
            self.addColumn("tv_episodes", "release_name", "TEXT", "")

        ep_results = self.connection.select("SELECT episode_id, location, file_size FROM tv_episodes")

        logger.log(u"Adding file size to all episodes in DB, please be patient")
        for cur_ep in ep_results:
            if not cur_ep["location"]:
                continue

            # if there is no size yet then populate it for us
            if (not cur_ep["file_size"] or not int(cur_ep["file_size"])) and ek.ek(os.path.isfile, cur_ep["location"]):
                cur_size = ek.ek(os.path.getsize, cur_ep["location"])
                self.connection.action("UPDATE tv_episodes SET file_size = ? WHERE episode_id = ?",
                                       [cur_size, int(cur_ep["episode_id"])])

        # check each snatch to see if we can use it to get a release name from
        history_results = self.connection.select("SELECT * FROM history WHERE provider != -1 ORDER BY date ASC")

        logger.log(u"Adding release name to all episodes still in history")
        for cur_result in history_results:
            # find the associated download, if there isn't one then ignore it
            download_results = self.connection.select(
                "SELECT resource FROM history WHERE provider = -1 AND showid = ? AND season = ? AND episode = ? AND date > ?",
                [cur_result["showid"], cur_result["season"], cur_result["episode"], cur_result["date"]])
            if not download_results:
                logger.log(u"Found a snatch in the history for " + cur_result[
                    "resource"] + " but couldn't find the associated download, skipping it", logger.DEBUG)
                continue

            nzb_name = cur_result["resource"]
            file_name = ek.ek(os.path.basename, download_results[0]["resource"])

            # take the extension off the filename, it's not needed
            if '.' in file_name:
                file_name = file_name.rpartition('.')[0]

            # find the associated episode on disk
            ep_results = self.connection.select(
                "SELECT episode_id, status FROM tv_episodes WHERE showid = ? AND season = ? AND episode = ? AND location != ''",
                [cur_result["showid"], cur_result["season"], cur_result["episode"]])
            if not ep_results:
                logger.log(
                    u"The episode " + nzb_name + " was found in history but doesn't exist on disk anymore, skipping",
                    logger.DEBUG)
                continue

            # get the status/quality of the existing ep and make sure it's what we expect
            ep_status, ep_quality = common.Quality.splitCompositeStatus(int(ep_results[0]["status"]))
            if ep_status != common.DOWNLOADED:
                continue

            if ep_quality != int(cur_result["quality"]):
                continue

            # make sure this is actually a real release name and not a season pack or something
            for cur_name in (nzb_name, file_name):
                logger.log(u"Checking if " + cur_name + " is actually a good release name", logger.DEBUG)
                try:
                    np = NameParser(False)
                    parse_result = np.parse(cur_name)
                except InvalidNameException:
                    continue

                if parse_result.series_name and parse_result.season_number != None and parse_result.episode_numbers and parse_result.release_group:
                    # if all is well by this point we'll just put the release name into the database
                    self.connection.action("UPDATE tv_episodes SET release_name = ? WHERE episode_id = ?",
                                           [cur_name, ep_results[0]["episode_id"]])
                    break

        # check each snatch to see if we can use it to get a release name from
        empty_results = self.connection.select("SELECT episode_id, location FROM tv_episodes WHERE release_name = ''")

        logger.log(u"Adding release name to all episodes with obvious scene filenames")
        for cur_result in empty_results:

            ep_file_name = ek.ek(os.path.basename, cur_result["location"])
            ep_file_name = os.path.splitext(ep_file_name)[0]

            # only want to find real scene names here so anything with a space in it is out
            if ' ' in ep_file_name:
                continue

            try:
                np = NameParser(False)
                parse_result = np.parse(ep_file_name)
            except InvalidNameException:
                continue

            if not parse_result.release_group:
                continue

            logger.log(
                u"Name " + ep_file_name + " gave release group of " + parse_result.release_group + ", seems valid",
                logger.DEBUG)
            self.connection.action("UPDATE tv_episodes SET release_name = ? WHERE episode_id = ?",
                                   [ep_file_name, cur_result["episode_id"]])

        self.incDBVersion()


class RenameSeasonFolders(AddSizeAndSceneNameFields):
    def test(self):
        return self.checkDBVersion() >= 11

    def execute(self):
        # rename the column
        self.connection.action("ALTER TABLE tv_shows RENAME TO tmp_tv_shows")
        self.connection.action(
            "CREATE TABLE tv_shows (show_id INTEGER PRIMARY KEY, location TEXT, show_name TEXT, tvdb_id NUMERIC, network TEXT, genre TEXT, runtime NUMERIC, quality NUMERIC, airs TEXT, status TEXT, flatten_folders NUMERIC, paused NUMERIC, startyear NUMERIC, tvr_id NUMERIC, tvr_name TEXT, air_by_date NUMERIC, lang TEXT)")
        sql = "INSERT INTO tv_shows(show_id, location, show_name, tvdb_id, network, genre, runtime, quality, airs, status, flatten_folders, paused, startyear, tvr_id, tvr_name, air_by_date, lang) SELECT show_id, location, show_name, tvdb_id, network, genre, runtime, quality, airs, status, seasonfolders, paused, startyear, tvr_id, tvr_name, air_by_date, lang FROM tmp_tv_shows"
        self.connection.action(sql)

        # flip the values to be opposite of what they were before
        self.connection.action("UPDATE tv_shows SET flatten_folders = 2 WHERE flatten_folders = 1")
        self.connection.action("UPDATE tv_shows SET flatten_folders = 1 WHERE flatten_folders = 0")
        self.connection.action("UPDATE tv_shows SET flatten_folders = 0 WHERE flatten_folders = 2")
        self.connection.action("DROP TABLE tmp_tv_shows")

        self.incDBVersion()


class Add1080pAndRawHDQualities(RenameSeasonFolders):
    """Add support for 1080p related qualities along with RawHD

    Quick overview of what the upgrade needs to do:

           quality   | old  | new
        --------------------------
        hdwebdl      | 1<<3 | 1<<5
        hdbluray     | 1<<4 | 1<<7
        fullhdbluray | 1<<5 | 1<<8
        --------------------------
        rawhdtv      |      | 1<<3
        fullhdtv     |      | 1<<4
        fullhdwebdl  |      | 1<<6
    """

    def test(self):
        return self.checkDBVersion() >= 12

    def _update_status(self, old_status):
        (status, quality) = common.Quality.splitCompositeStatus(old_status)
        return common.Quality.compositeStatus(status, self._update_quality(quality))

    def _update_quality(self, old_quality):
        """Update bitwise flags to reflect new quality values

        Check flag bits (clear old then set their new locations) starting
        with the highest bits so we dont overwrite data we need later on
        """

        result = old_quality
        # move fullhdbluray from 1<<5 to 1<<8 if set
        if (result & (1 << 5)):
            result = result & ~(1 << 5)
            result = result | (1 << 8)
        # move hdbluray from 1<<4 to 1<<7 if set
        if (result & (1 << 4)):
            result = result & ~(1 << 4)
            result = result | (1 << 7)
        # move hdwebdl from 1<<3 to 1<<5 if set
        if (result & (1 << 3)):
            result = result & ~(1 << 3)
            result = result | (1 << 5)

        return result

    def _update_composite_qualities(self, status):
        """Unpack, Update, Return new quality values

        Unpack the composite archive/initial values.
        Update either qualities if needed.
        Then return the new compsite quality value.
        """

        best = (status & (0xffff << 16)) >> 16
        initial = status & (0xffff)

        best = self._update_quality(best)
        initial = self._update_quality(initial)

        result = ((best << 16) | initial)
        return result

    def execute(self):
        backupDatabase(self.checkDBVersion())

        # update the default quality so we dont grab the wrong qualities after migration
        sickbeard.QUALITY_DEFAULT = self._update_composite_qualities(sickbeard.QUALITY_DEFAULT)
        sickbeard.save_config()

        # upgrade previous HD to HD720p -- shift previous qualities to new placevalues
        old_hd = common.Quality.combineQualities(
            [common.Quality.HDTV, common.Quality.HDWEBDL >> 2, common.Quality.HDBLURAY >> 3], [])
        new_hd = common.Quality.combineQualities([common.Quality.HDTV, common.Quality.HDWEBDL, common.Quality.HDBLURAY],
            [])

        # update ANY -- shift existing qualities and add new 1080p qualities, note that rawHD was not added to the ANY template
        old_any = common.Quality.combineQualities(
            [common.Quality.SDTV, common.Quality.SDDVD, common.Quality.HDTV, common.Quality.HDWEBDL >> 2,
             common.Quality.HDBLURAY >> 3, common.Quality.UNKNOWN], [])
        new_any = common.Quality.combineQualities(
            [common.Quality.SDTV, common.Quality.SDDVD, common.Quality.HDTV, common.Quality.FULLHDTV,
             common.Quality.HDWEBDL, common.Quality.FULLHDWEBDL, common.Quality.HDBLURAY, common.Quality.FULLHDBLURAY,
             common.Quality.UNKNOWN], [])

        # update qualities (including templates)
        logger.log(u"[1/4] Updating pre-defined templates and the quality for each show...", logger.MESSAGE)
        ql = []
        shows = self.connection.select("SELECT * FROM tv_shows")
        for cur_show in shows:
            if cur_show["quality"] == old_hd:
                new_quality = new_hd
            elif cur_show["quality"] == old_any:
                new_quality = new_any
            else:
                new_quality = self._update_composite_qualities(cur_show["quality"])
            ql.append(["UPDATE tv_shows SET quality = ? WHERE show_id = ?", [new_quality, cur_show["show_id"]]])
        self.connection.mass_action(ql)

        # update status that are are within the old hdwebdl (1<<3 which is 8) and better -- exclude unknown (1<<15 which is 32768)
        logger.log(u"[2/4] Updating the status for the episodes within each show...", logger.MESSAGE)
        ql = []
        episodes = self.connection.select("SELECT * FROM tv_episodes WHERE status < 3276800 AND status >= 800")
        for cur_episode in episodes:
            ql.append(["UPDATE tv_episodes SET status = ? WHERE episode_id = ?",
                       [self._update_status(cur_episode["status"]), cur_episode["episode_id"]]])
        self.connection.mass_action(ql)

        # make two seperate passes through the history since snatched and downloaded (action & quality) may not always coordinate together

        # update previous history so it shows the correct action
        logger.log(u"[3/4] Updating history to reflect the correct action...", logger.MESSAGE)
        ql = []
        historyAction = self.connection.select("SELECT * FROM history WHERE action < 3276800 AND action >= 800")
        for cur_entry in historyAction:
            ql.append(["UPDATE history SET action = ? WHERE showid = ? AND date = ?",
                       [self._update_status(cur_entry["action"]), cur_entry["showid"], cur_entry["date"]]])
        self.connection.mass_action(ql)

        # update previous history so it shows the correct quality
        logger.log(u"[4/4] Updating history to reflect the correct quality...", logger.MESSAGE)
        ql = []
        historyQuality = self.connection.select("SELECT * FROM history WHERE quality < 32768 AND quality >= 8")
        for cur_entry in historyQuality:
            ql.append(["UPDATE history SET quality = ? WHERE showid = ? AND date = ?",
                       [self._update_quality(cur_entry["quality"]), cur_entry["showid"], cur_entry["date"]]])
        self.connection.mass_action(ql)

        self.incDBVersion()

        # cleanup and reduce db if any previous data was removed
        logger.log(u"Performing a vacuum on the database.", logger.DEBUG)
        self.connection.action("VACUUM")


class AddShowidTvdbidIndex(Add1080pAndRawHDQualities):
    """ Adding index on tvdb_id (tv_shows) and showid (tv_episodes) to speed up searches/queries """

    def test(self):
        return self.checkDBVersion() >= 13

    def execute(self):
        backupDatabase(13)

        logger.log(u"Check for duplicate shows before adding unique index.")
        MainSanityCheck(self.connection).fix_duplicate_shows('tvdb_id')

        logger.log(u"Adding index on tvdb_id (tv_shows) and showid (tv_episodes) to speed up searches/queries.")
        if not self.hasTable("idx_showid"):
            self.connection.action("CREATE INDEX idx_showid ON tv_episodes (showid);")
        if not self.hasTable("idx_tvdb_id"):
            self.connection.action("CREATE UNIQUE INDEX idx_tvdb_id ON tv_shows (tvdb_id);")

        self.incDBVersion()


class AddLastUpdateTVDB(AddShowidTvdbidIndex):
    """ Adding column last_update_tvdb to tv_shows for controlling nightly updates """

    def test(self):
        return self.checkDBVersion() >= 14

    def execute(self):
        backupDatabase(14)

        logger.log(u"Adding column last_update_tvdb to tvshows")
        if not self.hasColumn("tv_shows", "last_update_tvdb"):
            self.addColumn("tv_shows", "last_update_tvdb", default=1)

        self.incDBVersion()


class AddDBIncreaseTo15(AddLastUpdateTVDB):
    def test(self):
        return self.checkDBVersion() >= 15

    def execute(self):
        self.incDBVersion()


class AddIMDbInfo(AddDBIncreaseTo15):
    def test(self):
        return self.checkDBVersion() >= 16

    def execute(self):
        self.connection.action(
            "CREATE TABLE imdb_info (tvdb_id INTEGER PRIMARY KEY, imdb_id TEXT, title TEXT, year NUMERIC, akas TEXT, runtimes NUMERIC, genres TEXT, countries TEXT, country_codes TEXT, certificates TEXT, rating TEXT, votes INTEGER, last_update NUMERIC)")

        if not self.hasColumn("tv_shows", "imdb_id"):
            self.addColumn("tv_shows", "imdb_id")

        self.incDBVersion()


class AddProperNamingSupport(AddIMDbInfo):
    def test(self):
        return self.checkDBVersion() >= 17

    def execute(self):
        self.addColumn("tv_episodes", "is_proper")
        self.incDBVersion()


class AddEmailSubscriptionTable(AddProperNamingSupport):
    def test(self):
        return self.checkDBVersion() >= 18

    def execute(self):
        self.addColumn('tv_shows', 'notify_list', 'TEXT', None)
        self.incDBVersion()


class AddProperSearch(AddEmailSubscriptionTable):
    def test(self):
        return self.checkDBVersion() >= 19

    def execute(self):
        backupDatabase(19)

        logger.log(u"Adding column last_proper_search to info")
        if not self.hasColumn("info", "last_proper_search"):
            self.addColumn("info", "last_proper_search", default=1)

        self.incDBVersion()


class AddDvdOrderOption(AddProperSearch):
    def test(self):
        return self.checkDBVersion() >= 20

    def execute(self):
        logger.log(u"Adding column dvdorder to tvshows")
        if not self.hasColumn("tv_shows", "dvdorder"):
            self.addColumn("tv_shows", "dvdorder", "NUMERIC", "0")

        self.incDBVersion()


class AddSubtitlesSupport(AddDvdOrderOption):
    def test(self):
        return self.checkDBVersion() >= 21

    def execute(self):
        if not self.hasColumn("tv_shows", "subtitles"):
            self.addColumn("tv_shows", "subtitles")
            self.addColumn("tv_episodes", "subtitles", "TEXT", "")
            self.addColumn("tv_episodes", "subtitles_searchcount")
            self.addColumn("tv_episodes", "subtitles_lastsearch", "TIMESTAMP", str(datetime.datetime.min))
        self.incDBVersion()


class ConvertTVShowsToIndexerScheme(AddSubtitlesSupport):
    def test(self):
        return self.checkDBVersion() >= 22

    def execute(self):
        backupDatabase(22)

        logger.log(u"Converting TV Shows table to Indexer Scheme...")

        if self.hasTable("tmp_tv_shows"):
            logger.log(u"Removing temp tv show tables left behind from previous updates...")
            self.connection.action("DROP TABLE tmp_tv_shows")

        self.connection.action("ALTER TABLE tv_shows RENAME TO tmp_tv_shows")
        self.connection.action(
            "CREATE TABLE tv_shows (show_id INTEGER PRIMARY KEY, indexer_id NUMERIC, indexer NUMERIC, show_name TEXT, location TEXT, network TEXT, genre TEXT, classification TEXT, runtime NUMERIC, quality NUMERIC, airs TEXT, status TEXT, flatten_folders NUMERIC, paused NUMERIC, startyear NUMERIC, air_by_date NUMERIC, lang TEXT, subtitles NUMERIC, notify_list TEXT, imdb_id TEXT, last_update_indexer NUMERIC, dvdorder NUMERIC)")
        self.connection.action(
            "INSERT INTO tv_shows(show_id, indexer_id, show_name, location, network, genre, runtime, quality, airs, status, flatten_folders, paused, startyear, air_by_date, lang, subtitles, notify_list, imdb_id, last_update_indexer, dvdorder) SELECT show_id, tvdb_id, show_name, location, network, genre, runtime, quality, airs, status, flatten_folders, paused, startyear, air_by_date, lang, subtitles, notify_list, imdb_id, last_update_tvdb, dvdorder FROM tmp_tv_shows")
        self.connection.action("DROP TABLE tmp_tv_shows")

        self.connection.action("CREATE UNIQUE INDEX idx_indexer_id ON tv_shows (indexer_id);")

        self.connection.action("UPDATE tv_shows SET classification = 'Scripted'")
        self.connection.action("UPDATE tv_shows SET indexer = 1")

        self.incDBVersion()


class ConvertTVEpisodesToIndexerScheme(ConvertTVShowsToIndexerScheme):
    def test(self):
        return self.checkDBVersion() >= 23

    def execute(self):
        backupDatabase(23)

        logger.log(u"Converting TV Episodes table to Indexer Scheme...")

        if self.hasTable("tmp_tv_episodes"):
            logger.log(u"Removing temp tv episode tables left behind from previous updates...")
            self.connection.action("DROP TABLE tmp_tv_episodes")

        self.connection.action("ALTER TABLE tv_episodes RENAME TO tmp_tv_episodes")
        self.connection.action(
            "CREATE TABLE tv_episodes (episode_id INTEGER PRIMARY KEY, showid NUMERIC, indexerid NUMERIC, indexer NUMERIC, name TEXT, season NUMERIC, episode NUMERIC, description TEXT, airdate NUMERIC, hasnfo NUMERIC, hastbn NUMERIC, status NUMERIC, location TEXT, file_size NUMERIC, release_name TEXT, subtitles TEXT, subtitles_searchcount NUMERIC, subtitles_lastsearch TIMESTAMP, is_proper NUMERIC)")
        self.connection.action(
            "INSERT INTO tv_episodes(episode_id, showid, indexerid, name, season, episode, description, airdate, hasnfo, hastbn, status, location, file_size, release_name, subtitles, subtitles_searchcount, subtitles_lastsearch, is_proper) SELECT episode_id, showid, tvdbid, name, season, episode, description, airdate, hasnfo, hastbn, status, location, file_size, release_name, subtitles, subtitles_searchcount, subtitles_lastsearch, is_proper FROM tmp_tv_episodes")
        self.connection.action("DROP TABLE tmp_tv_episodes")

        self.connection.action("CREATE INDEX idx_tv_episodes_showid_airdate ON tv_episodes(showid,airdate);")
        self.connection.action("CREATE INDEX idx_showid ON tv_episodes (showid);")
        self.connection.action("CREATE INDEX idx_status ON tv_episodes (status,season,episode,airdate)")
        self.connection.action("CREATE INDEX idx_sta_epi_air ON tv_episodes (status,episode, airdate)")
        self.connection.action("CREATE INDEX idx_sta_epi_sta_air ON tv_episodes (season,episode, status, airdate)")

        self.connection.action("UPDATE tv_episodes SET indexer = 1")

        self.incDBVersion()


class ConvertIMDBInfoToIndexerScheme(ConvertTVEpisodesToIndexerScheme):
    def test(self):
        return self.checkDBVersion() >= 24

    def execute(self):
        backupDatabase(24)

        logger.log(u"Converting IMDB Info table to Indexer Scheme...")

        if self.hasTable("tmp_imdb_info"):
            logger.log(u"Removing temp imdb info tables left behind from previous updates...")
            self.connection.action("DROP TABLE tmp_imdb_info")

        self.connection.action("ALTER TABLE imdb_info RENAME TO tmp_imdb_info")
        self.connection.action(
            "CREATE TABLE imdb_info (indexer_id INTEGER PRIMARY KEY, imdb_id TEXT, title TEXT, year NUMERIC, akas TEXT, runtimes NUMERIC, genres TEXT, countries TEXT, country_codes TEXT, certificates TEXT, rating TEXT, votes INTEGER, last_update NUMERIC)")
        self.connection.action(
            "INSERT INTO imdb_info(indexer_id, imdb_id, title, year, akas, runtimes, genres, countries, country_codes, certificates, rating, votes, last_update) SELECT tvdb_id, imdb_id, title, year, akas, runtimes, genres, countries, country_codes, certificates, rating, votes, last_update FROM tmp_imdb_info")
        self.connection.action("DROP TABLE tmp_imdb_info")

        self.incDBVersion()


class ConvertInfoToIndexerScheme(ConvertIMDBInfoToIndexerScheme):
    def test(self):
        return self.checkDBVersion() >= 25

    def execute(self):
        backupDatabase(25)

        logger.log(u"Converting Info table to Indexer Scheme...")

        if self.hasTable("tmp_info"):
            logger.log(u"Removing temp info tables left behind from previous updates...")
            self.connection.action("DROP TABLE tmp_info")

        self.connection.action("ALTER TABLE info RENAME TO tmp_info")
        self.connection.action(
            "CREATE TABLE info (last_backlog NUMERIC, last_indexer NUMERIC, last_proper_search NUMERIC)")
        self.connection.action(
            "INSERT INTO info(last_backlog, last_indexer, last_proper_search) SELECT last_backlog, last_tvdb, last_proper_search FROM tmp_info")
        self.connection.action("DROP TABLE tmp_info")

        self.incDBVersion()


class AddArchiveFirstMatchOption(ConvertInfoToIndexerScheme):
    def test(self):
        return self.checkDBVersion() >= 26

    def execute(self):
        backupDatabase(26)

        logger.log(u"Adding column archive_firstmatch to tvshows")
        if not self.hasColumn("tv_shows", "archive_firstmatch"):
            self.addColumn("tv_shows", "archive_firstmatch", "NUMERIC", "0")

        self.incDBVersion()


class AddSceneNumbering(AddArchiveFirstMatchOption):
    def test(self):
        return self.checkDBVersion() >= 27

    def execute(self):
        backupDatabase(27)

        if self.hasTable("scene_numbering"):
            self.connection.action("DROP TABLE scene_numbering")

        self.connection.action(
            "CREATE TABLE scene_numbering (indexer TEXT, indexer_id INTEGER, season INTEGER, episode INTEGER, scene_season INTEGER, scene_episode INTEGER, PRIMARY KEY (indexer_id, season, episode, scene_season, scene_episode))")

        self.incDBVersion()


class ConvertIndexerToInteger(AddSceneNumbering):
    def test(self):
        return self.checkDBVersion() >= 28

    def execute(self):
        backupDatabase(28)

        ql = []
        logger.log(u"Converting Indexer to Integer ...", logger.MESSAGE)
        ql.append(["UPDATE tv_shows SET indexer = ? WHERE LOWER(indexer) = ?", ["1", "tvdb"]])
        ql.append(["UPDATE tv_shows SET indexer = ? WHERE LOWER(indexer) = ?", ["2", "tvrage"]])
        ql.append(["UPDATE tv_episodes SET indexer = ? WHERE LOWER(indexer) = ?", ["1", "tvdb"]])
        ql.append(["UPDATE tv_episodes SET indexer = ? WHERE LOWER(indexer) = ?", ["2", "tvrage"]])
        ql.append(["UPDATE scene_numbering SET indexer = ? WHERE LOWER(indexer) = ?", ["1", "tvdb"]])
        ql.append(["UPDATE scene_numbering SET indexer = ? WHERE LOWER(indexer) = ?", ["2", "tvrage"]])

        self.connection.mass_action(ql)

        self.incDBVersion()


class AddRequireAndIgnoreWords(ConvertIndexerToInteger):
    """ Adding column rls_require_words and rls_ignore_words to tv_shows """

    def test(self):
        return self.checkDBVersion() >= 29

    def execute(self):
        backupDatabase(29)

        logger.log(u"Adding column rls_require_words to tvshows")
        if not self.hasColumn("tv_shows", "rls_require_words"):
            self.addColumn("tv_shows", "rls_require_words", "TEXT", "")

        logger.log(u"Adding column rls_ignore_words to tvshows")
        if not self.hasColumn("tv_shows", "rls_ignore_words"):
            self.addColumn("tv_shows", "rls_ignore_words", "TEXT", "")

        self.incDBVersion()


class AddSportsOption(AddRequireAndIgnoreWords):
    def test(self):
        return self.checkDBVersion() >= 30

    def execute(self):
        backupDatabase(30)

        logger.log(u"Adding column sports to tvshows")
        if not self.hasColumn("tv_shows", "sports"):
            self.addColumn("tv_shows", "sports", "NUMERIC", "0")

        if self.hasColumn("tv_shows", "air_by_date") and self.hasColumn("tv_shows", "sports"):
            # update sports column
            logger.log(u"[4/4] Updating tv_shows to reflect the correct sports value...", logger.MESSAGE)
            ql = []
            historyQuality = self.connection.select(
                "SELECT * FROM tv_shows WHERE LOWER(classification) = 'sports' AND air_by_date = 1 AND sports = 0")
            for cur_entry in historyQuality:
                ql.append(["UPDATE tv_shows SET sports = ? WHERE show_id = ?",
                           [cur_entry["air_by_date"], cur_entry["show_id"]]])
                ql.append(["UPDATE tv_shows SET air_by_date = 0 WHERE show_id = ?", [cur_entry["show_id"]]])
            self.connection.mass_action(ql)

        self.incDBVersion()


class AddSceneNumberingToTvEpisodes(AddSportsOption):
    def test(self):
        return self.checkDBVersion() >= 31

    def execute(self):
        backupDatabase(31)

        logger.log(u"Adding column scene_season and scene_episode to tvepisodes")
        self.addColumn("tv_episodes", "scene_season", "NUMERIC", "NULL")
        self.addColumn("tv_episodes", "scene_episode", "NUMERIC", "NULL")

        self.incDBVersion()

class AddAnimeTVShow(AddSceneNumberingToTvEpisodes):
    def test(self):
        return self.checkDBVersion() >= 32

    def execute(self):
        backupDatabase(32)

        logger.log(u"Adding column anime to tv_episodes")
        self.addColumn("tv_shows", "anime", "NUMERIC", "0")

        self.incDBVersion()

class AddAbsoluteNumbering(AddAnimeTVShow):
    def test(self):
        return self.checkDBVersion() >= 33

    def execute(self):
        backupDatabase(33)

        logger.log(u"Adding column absolute_number to tv_episodes")
        self.addColumn("tv_episodes", "absolute_number", "NUMERIC", "0")

        self.incDBVersion()

class AddSceneAbsoluteNumbering(AddAbsoluteNumbering):
    def test(self):
        return self.checkDBVersion() >= 34

    def execute(self):
        backupDatabase(34)

        logger.log(u"Adding column absolute_number and scene_absolute_number to scene_numbering")
        self.addColumn("scene_numbering", "absolute_number", "NUMERIC", "0")
        self.addColumn("scene_numbering", "scene_absolute_number", "NUMERIC", "0")

        self.incDBVersion()

class AddAnimeBlacklistWhitelist(AddSceneAbsoluteNumbering):

    def test(self):
        return self.checkDBVersion() >= 35

    def execute(self):
        backupDatabase(35)

        ql = []
        ql.append(["CREATE TABLE blacklist (show_id INTEGER, range TEXT, keyword TEXT)"])
        ql.append(["CREATE TABLE whitelist (show_id INTEGER, range TEXT, keyword TEXT)"])
        self.connection.mass_action(ql)

        self.incDBVersion()

class AddSceneAbsoluteNumbering(AddAnimeBlacklistWhitelist):
    def test(self):
        return self.checkDBVersion() >= 36

    def execute(self):
        backupDatabase(36)

        logger.log(u"Adding column scene_absolute_number to tv_episodes")
        self.addColumn("tv_episodes", "scene_absolute_number", "NUMERIC", "0")

        self.incDBVersion()

class AddXemRefresh(AddSceneAbsoluteNumbering):
    def test(self):
        return self.checkDBVersion() >= 37

    def execute(self):
        backupDatabase(37)

        logger.log(u"Creating table xem_refresh")
        self.connection.action(
            "CREATE TABLE xem_refresh (indexer TEXT, indexer_id INTEGER PRIMARY KEY, last_refreshed INTEGER)")

        self.incDBVersion()

class AddSceneToTvShows(AddXemRefresh):
    def test(self):
        return self.checkDBVersion() >= 38

    def execute(self):
        backupDatabase(38)

        logger.log(u"Adding column scene to tv_shows")
        self.addColumn("tv_shows", "scene", "NUMERIC", "0")

        self.incDBVersion()

