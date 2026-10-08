def find_target_playlist(name, playlists):
    target_name = name.strip().casefold()

    matching_playlists = []
    for playlist in playlists:
        play_name = playlist["name"].strip().casefold()
        if play_name == target_name:
            matching_playlists.append(playlist)

    if len(matching_playlists) > 1:
        raise ValueError("More than one matching playlists")

    if matching_playlists:
        return matching_playlists[0]
    
    return None

