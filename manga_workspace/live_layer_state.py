"""RT ownership is a layer UUID, never a panel index or a layer name."""
import json

KEY = 'manga_workspace/live-layers-v1'


def read_states(document):
    try:
        value = json.loads(bytes(document.annotation(KEY)))
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def owner_id(states, selected_id):
    if selected_id in states:
        return selected_id
    for uid, state in states.items():
        if isinstance(state, dict) and selected_id == state.get('sketch'):
            return uid
    return selected_id


def settings_snapshot(model):
    return dict(positive=model.regions.positive, negative=model.regions.negative,
                style=model.style.filename, seed=model.seed, strength=model.live.strength)


def apply_settings(model, values, find_style):
    model.regions.positive = values.get('positive', '')
    model.regions.negative = values.get('negative', '')
    style = find_style(values.get('style', ''))
    if style is not None:
        model.style = style
    model.seed = int(values.get('seed', 0))
    model.live.strength = float(values.get('strength', 0.3))
