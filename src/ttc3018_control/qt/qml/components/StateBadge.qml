import QtQuick
import QtQuick.Controls

Rectangle {
    id: root
    required property string label
    property string status: "required"
    property var palette
    implicitWidth: badgeLabel.implicitWidth + 22
    implicitHeight: 28
    radius: 14
    color: Qt.rgba(tone.r, tone.g, tone.b, 0.14)
    border.color: Qt.rgba(tone.r, tone.g, tone.b, 0.42)
    border.width: 1

    readonly property color tone: status === "complete" ? palette.success
        : status === "working" ? palette.accent
        : status === "warning" ? palette.warning
        : status === "unavailable" ? palette.subtle : palette.muted

    Label {
        id: badgeLabel
        anchors.centerIn: parent
        text: root.label
        color: root.tone
        font.pixelSize: 11
        font.weight: Font.DemiBold
    }
}
