import QtQuick
import QtQuick.Controls

Item {
    id: root
    property bool active: false
    property string message: "Working…"
    visible: active
    Rectangle { anchors.fill: parent; color: "#99181A1F"; radius: 9 }
    Column {
        anchors.centerIn: parent
        spacing: 8
        BusyIndicator { anchors.horizontalCenter: parent.horizontalCenter; running: root.active }
        Label { text: root.message; color: "white" }
    }
}
