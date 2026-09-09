"""A replaceable view of current equipment. No event log or removed-item history."""
import copy


def occupied_main_slots(decoded, capacity=60):
    """All non-empty item kinds occupy a slot, even when hidden by loot filters."""
    return [index for index, item in enumerate(decoded[:capacity])
            if item.get('物品类型', item.get('种类', 0)) != 0]


class CurrentInventory:
    def __init__(self):
        self.slots = {}

    def replace(self, slots):
        changed = self.slots != slots
        self.slots = copy.deepcopy(slots)
        return changed

    def clear(self):
        self.slots = {}

    def export(self):
        return [{"index": index, "item": copy.deepcopy(item)}
                for index, item in sorted(self.slots.items())]
