// Basit global toast — context plumbing yok. Her yerden `toast(msg, type)`.
// type: ok | error | info. ToastHost dinler ve sağ-üstte gösterir.
let _id = 0;
const listeners = new Set();
let items = [];

function emit() {
  listeners.forEach((fn) => fn(items));
}

export function toast(message, type = "info", ttl = 3500) {
  const id = ++_id;
  items = [...items, { id, message, type }];
  emit();
  if (ttl > 0) setTimeout(() => dismiss(id), ttl);
  return id;
}

export function dismiss(id) {
  items = items.filter((t) => t.id !== id);
  emit();
}

export function subscribe(fn) {
  listeners.add(fn);
  fn(items);
  return () => listeners.delete(fn);
}
