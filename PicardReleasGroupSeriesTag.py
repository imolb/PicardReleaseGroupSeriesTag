PLUGIN_NAME = "Release Group Series Tag"
PLUGIN_AUTHOR = "imolb"
PLUGIN_DESCRIPTION = """
The plugin sets a user defined tag TXXX:releasegroupseries indicating the release group series from MusicBrainz databse.
"""
PLUGIN_VERSION = '0.1'
PLUGIN_API_VERSIONS = ['2.0', '2.1', '2.2']
PLUGIN_LICENSE = "GPL-2.0"
PLUGIN_LICENSE_URL = "https://www.gnu.org/licenses/gpl-2.0.html"
# Plugin created 2021 by modification of the metabrain/picard-plugins/albumartist_website plugin
# https://github.com/metabrainz/picard-plugins/blob/2.0/plugins/albumartist_website/albumartist_website.py

USER_DEFINED_TAG_NAME = "releasegroupseries"

from picard import config, log
from picard.util import LockableObject
from picard.metadata import register_track_metadata_processor
from functools import partial

class ReleaseGroupSeriesTag:

    class ReleaseGroupSeriesQueue(LockableObject):

        def __init__(self):
            LockableObject.__init__(self)
            self.queue = {}

        def __contains__(self, name):
            return name in self.queue

        def __iter__(self):
            return self.queue.__iter__()

        def __getitem__(self, name):
            self.lock_for_read()
            value = self.queue[name] if name in self.queue else None
            self.unlock()
            return value

        def __setitem__(self, name, value):
            self.lock_for_write()
            self.queue[name] = value
            self.unlock()

        def append(self, name, value):
            self.lock_for_write()
            if name in self.queue:
                self.queue[name].append(value)
                value = False
            else:
                self.queue[name] = [value]
                value = True
            self.unlock()
            return value

        def remove(self, name):
            self.lock_for_write()
            value = None
            if name in self.queue:
                value = self.queue[name]
                del self.queue[name]
            self.unlock()
            return value

    def __init__(self):
        self.series_cache = {}
        self.series_queue = self.ReleaseGroupSeriesQueue()

    def add_release_group_series(self, album, track_metadata, track_node, release_node):
        releaseGroupIds = track_metadata.getall('musicbrainz_releasegroupid')
        for releaseId in releaseGroupIds:
            if releaseId in self.series_cache:
                if self.series_cache[releaseId]:
                    track_metadata[USER_DEFINED_TAG_NAME] = self.series_cache[releaseId]
            else:
                # Jump through hoops to get track object!!
                self.website_add_track(album, album._new_tracks[-1], releaseId)

    def website_add_track(self, album, track, releaseId):
        self.album_add_request(album)
        if self.series_queue.append(releaseId, (track, album)):
            host = config.setting["server_host"]
            port = config.setting["server_port"]
            path = "/ws/2/%s/%s" % ('release-group', releaseId)
            queryargs = {"inc": "series-rels"}
            return album.tagger.webservice.get(host, port, path,
                        partial(self.series_process, releaseId),
                                parse_response_type="xml", priority=True, important=False,
                                queryargs=queryargs)

    def series_process(self, releaseId, response, reply, error):
        if error:
            log.error("%s: %r: Network error retrieving release-group record", PLUGIN_NAME, releaseId)
            tuples = self.series_queue.remove(releaseId)
            for track, album in tuples:
                self.album_remove_request(album)
            return
        series = self.release_group_process_metadata(releaseId, response)
        self.series_cache[releaseId] = series
        tuples = self.series_queue.remove(releaseId)
        for track, album in tuples:
            if series:
                tm = track.metadata
                tm[USER_DEFINED_TAG_NAME] = series
                for file in track.iterfiles(True):
                    fm = file.metadata
                    fm[USER_DEFINED_TAG_NAME] = series
            self.album_remove_request(album)

    def album_add_request(self, album):
        album._requests += 1

    def album_remove_request(self, album):
        album._requests -= 1
        album._finalize_loading(None)

    def release_group_process_metadata(self, releaseId, response):
        log.debug("%s: %r: Processing Release-Group record for related series: %r", PLUGIN_NAME, releaseId, response)
        relations = self.release_group_get_relations(response)
        if not relations:
            log.info("%s: %r: Release-Group does have any associated series.", PLUGIN_NAME, releaseId)
            return []

        series = []
        for relation in relations:
            log.debug("%s: %r: Examining: %r", PLUGIN_NAME, releaseId, relation)
            if 'type' in relation.attribs and relation.type == 'part of':
                if 'series' in relation.children:
                    if 'name' in relation.series[0].children and len(relation.series[0].name[0].text) > 0:
                        log.debug("%s: Adding series: %s", PLUGIN_NAME, relation.series[0].name[0].text)
                        series.append(relation.series[0].name[0].text)
                else:
                    log.debug("%s: No series in relation: %r", PLUGIN_NAME, relation)

        if series:
            log.info("%s: %r: Release-Group series: %r", PLUGIN_NAME, releaseId, series)
        else:
            log.info("%s: %r: Release-Group does not have any related series.", PLUGIN_NAME, releaseId)
        return sorted(series)

    def release_group_get_relations(self, response):
        log.debug("%s: release_group_get_relations called", PLUGIN_NAME)
        if 'metadata' in response.children and len(response.metadata) > 0:
            if 'release_group' in response.metadata[0].children and len(response.metadata[0].release_group) > 0:
                if 'relation_list' in response.metadata[0].release_group[0].children and len(response.metadata[0].release_group[0].relation_list) > 0:
                    if 'relation' in response.metadata[0].release_group[0].relation_list[0].children:
                        log.debug("%s: release_group_get_relations returning: %r", PLUGIN_NAME, response.metadata[0].release_group[0].relation_list[0].relation)
                        return response.metadata[0].release_group[0].relation_list[0].relation
                    else:
                        log.debug("%s: release_group_get_relations - no relation in relation_list", PLUGIN_NAME)
                else:
                    log.debug("%s: release_group_get_relations - no relation_list in release_group", PLUGIN_NAME)
            else:
                log.debug("%s: release_group_get_relations - no release_group in metadata", PLUGIN_NAME)
        else:
            log.debug("%s: release_group_get_relations - no metadata in response", PLUGIN_NAME)
        return None


register_track_metadata_processor(ReleaseGroupSeriesTag().add_release_group_series)