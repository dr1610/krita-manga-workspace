"""Compose optional RT tags without modifying the user's source prompt."""


def effective_prompt(text, monochrome_sketch=False, lineart=False):
    if not monochrome_sketch and not lineart:
        return text
    tags = {part.strip().casefold() for part in text.split(',')}
    additions = [tag for tag in ('monochrome', 'lineart' if lineart else 'sketch') if tag not in tags]
    if not additions:
        return text
    source = text.rstrip()
    separator = ' ' if source.endswith(',') else ', ' if source else ''
    return source + separator + ', '.join(additions)
