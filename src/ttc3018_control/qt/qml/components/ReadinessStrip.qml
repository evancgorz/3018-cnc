import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    required property var palette
    required property var entries
    signal activated(string action)
    implicitHeight: 45
    radius: 10
    color: palette.raised
    border.color: palette.divider
    border.width: 1
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 11
        anchors.rightMargin: 11
        spacing: 5
        Repeater {
            model: root.entries
            delegate: Button {
                required property var modelData
                Layout.fillWidth: true
                Layout.fillHeight: true
                flat: true
                text: modelData.label + "  " + (modelData.status === "complete" ? "✓" : modelData.status === "working" ? "…" : "!")
                font.pixelSize: 11
                font.weight: Font.DemiBold
                contentItem: Text {
                    text: parent.text
                    color: modelData.status === "complete" ? root.palette.success : modelData.status === "working" ? root.palette.accent : modelData.status === "warning" ? root.palette.warning : root.palette.muted
                    font: parent.font
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                background: Rectangle { radius: 7; color: parent.hovered ? root.palette.hover : "transparent" }
                ToolTip.visible: hovered
                ToolTip.text: modelData.reason
                onClicked: root.activated(modelData.action)
            }
        }
    }
}
