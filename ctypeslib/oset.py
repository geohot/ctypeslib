class OSet:
  def __init__(self):
    self.dict = {}
  def add(self, v):
    self.dict[v] = None
  def update(self, other):
    self.dict.update({k: None for k in other})
  def remove(self, v):
    del self.dict[v]
  def discard(self, v):
    if v in self.dict:
      del self.dict[v]
  def __contains__(self, item):
    return item in self.dict
  def __iter__(self):
    return iter(self.dict.keys())
  def __len__(self):
    return len(self.dict)
