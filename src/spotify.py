def get_spotify_playlists(spotify):
    playlists = []
    page = spotify.current_user_playlists(limit=50)

    while page is not None:
        playlists.extend(page["items"])
        if page["next"] is not None:
            page = spotify.next(page)
        else:
            page = None

    return playlists