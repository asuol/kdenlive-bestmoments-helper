"""
Steps done by this script:

- identify chains (represent video/audio clips imported into a kdenlive project)
- identify tractors (use tractors to determine if a playlist is mute)
- identify valid playlists (playlists that are not muted and that actually represent timeline tracks on kdenlive)
- for each playlist, place each clip into the playlist timeline, keeping each clip in and out times
- parse input file to determine clip and offset
"""
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from bisect import insort_right, bisect_right
from operator import attrgetter
import yaml
import argparse


class timeline_obj:
    def __init__(self, chain_id: str, timeline_in: datetime,
                 chain_in: datetime,
                 chain_out: datetime):
        self.chain_id = chain_id
        self.timeline_in = timeline_in
        self.chain_in = chain_in
        self.chain_out = chain_out

    def __lt__(self, other):
        return self.timeline_in < other.timeline_in

    def length(self):
        return self.chain_out - self.chain_in 

class playlist:
    def __init__(self, playlist_xml_obj: ET.Element):
        self.id = playlist_xml_obj.attrib["id"]
        self.timeline = []
        current_time=datetime.strptime('0:0:0.0', '%H:%M:%S.%f')
        self.is_valid = False

        if self.id == "main_bin":
            return

        for child in playlist_xml_obj:
            match child.tag:
                case "blank":
                    blank_time = datetime.strptime(child.attrib["length"], '%H:%M:%S.%f')
                    delta = current_time + timedelta(hours=blank_time.hour,
                                                     minutes=blank_time.minute,
                                                     seconds=blank_time.second,
                                                     microseconds=blank_time.microsecond)
                    current_time = delta
                case "entry":
                    chain_id = child.attrib["producer"]

                    if not chain_id.startswith("chain"):
                        continue

                    chain_in = datetime.strptime(child.attrib["in"], '%H:%M:%S.%f')
                    chain_out = datetime.strptime(child.attrib["out"], '%H:%M:%S.%f')

                    new_entry = timeline_obj(chain_id, current_time, chain_in, chain_out)

                    entry_len = new_entry.length()
                    delta = current_time + entry_len
                    current_time = delta

                    insort_right(self.timeline, new_entry)

                    self.is_valid = True
    def seek_chains(self, start: datetime, end: datetime):
        start_index = bisect_right(self.timeline, start, key=attrgetter("timeline_in")) - 1

        results = [self.timeline[start_index]]

        for i in range(start_index+1, len(self.timeline)):
            if self.timeline[i].timeline_in < end:
                results.append(self.timeline[i])

        return results


def parse_kdenlive_project(project_file: str):
    tree = ET.parse(project_file)

    chains = {}
    playlists = {}
    playlist_hide_status = {}

    for child in tree.getroot():
        match child.tag:
            case "chain":
                chain_id = child.attrib["id"]

                for prop in child:
                    if prop.tag == "property" and prop.attrib["name"] == "resource":
                        chain_filename = prop.text
                        break

                chains[chain_id] = chain_filename
            case "playlist":
                playlist_id = child.attrib["id"]

                new_playlist = playlist(child)

                if new_playlist.is_valid:
                    playlists[playlist_id] = new_playlist
            case "tractor":
                for prop in child:
                    if prop.tag == "track":
                        playlist_id = prop.attrib["producer"]
                        if "hide" in prop.attrib:
                            status = prop.attrib["hide"]

                            playlist_hide_status[playlist_id] = status
                
    # remove muted playlists
    muted_playlists = []
    for id, _ in playlists.items():
        if playlist_hide_status[id] == "both":
            muted_playlists.append(id)

    for id in muted_playlists:
        del playlists[id]

    return (chains, playlists)

if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("-f", help="yaml file with clips and timestamps",
                            type=str, dest="times_file")
    args = arg_parser.parse_args()

    # Parse clip instructions
    with open(args.times_file, 'r') as times_file:
        instructions = yaml.safe_load(times_file)
        for day in instructions:
            chains, playlists = parse_kdenlive_project(f"{day}.kdenlive")

            start_str = instructions[day]["clip"]["start"]
            end_str = instructions[day]["clip"]["end"]

            start = datetime.strptime(start_str, '%M:%S')
            end = datetime.strptime(end_str, '%M:%S')

            length = end - start
            output = {}
            for id, playlist in playlists.items():
                timeline_objs = playlist.seek_chains(start, end)

                for t in timeline_objs:
                    chain_id = t.chain_id
                    start_offset = start - t.timeline_in
                    chain_start = t.chain_in + start_offset

                    if t.length() < length:
                        chain_end = t.chain_out
                    else:
                        chain_end = chain_start + length

                    clip = {"clip": {
                        "start": chain_start.strftime('%H:%M:%S.%f')[:-3],
                        "end": chain_end.strftime('%H:%M:%S.%f')[:-3]
                        }
                    }

                    clip_name = chains[chain_id]
                    
                    if clip_name in output:
                        output[clip_name].append(clip)
                    else:
                        output[clip_name] = [clip]

            print(output)

            with open("sample_output.yaml", "w") as w:
                yaml.dump(output, w)
