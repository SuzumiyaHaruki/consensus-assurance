from importlib.resources import files


def knowledge():
    return files(__package__).joinpath("knowledge.txt").read_text()
