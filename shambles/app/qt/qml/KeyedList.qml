// A list of keys for a Repeater, kept in step with the view by key.
//
// A Repeater given a plain array makes every delegate again whenever the
// array is replaced, and the view is replaced every time it is worked out
// again: an open menu would close, keyboard focus and a tooltip would go.
// Given this instead, an account whose key is still there keeps its
// delegate, and only what was added, removed or moved changes. Each
// delegate looks its data up by ``model.key``.
import QtQuick

ListModel {
    id: root

    function sync(keys) {
        for (var i = root.count - 1; i >= 0; i--) {
            if (keys.indexOf(root.get(i).key) < 0)
                root.remove(i)
        }
        for (var j = 0; j < keys.length; j++) {
            var at = -1
            for (var k = j; k < root.count; k++) {
                if (root.get(k).key === keys[j]) {
                    at = k
                    break
                }
            }
            if (at < 0)
                root.insert(j, {"key": keys[j]})
            else if (at !== j)
                root.move(at, j, 1)
        }
    }
}
