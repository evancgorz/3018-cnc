import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    property var palette: ({ danger: "#ED5B5B", text: "#F2F4F7", muted: "#A8AFBA" })
    readonly property color dangerColor: palette && palette.danger ? palette.danger : "#ED5B5B"
    readonly property color textColor: palette && palette.text ? palette.text : "#F2F4F7"
    readonly property color mutedColor: palette && palette.muted ? palette.muted : "#A8AFBA"
    property bool active: false
    property string title: ""
    property string explanation: ""
    property var actions: []
    signal actionRequested(string action)
    visible: active
    implicitHeight: 68
    radius: 10
    color: Qt.rgba(dangerColor.r, dangerColor.g, dangerColor.b, 0.12)
    border.color: Qt.rgba(dangerColor.r, dangerColor.g, dangerColor.b, 0.48)
    border.width: 1
    RowLayout {
        anchors.fill: parent
        anchors.margins: 11
        spacing: 10
        Label { text: "!"; color: root.dangerColor; font.pixelSize: 21; font.bold: true }
        ColumnLayout { Layout.fillWidth: true; spacing: 2
            Label { text: root.title; color: root.textColor; font.weight: Font.DemiBold }
            Label { text: root.explanation; color: root.mutedColor; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true; maximumLineCount: 2; elide: Text.ElideRight }
        }
        Repeater { model: root.actions.slice(0, 2); delegate: Button { required property string modelData; text: modelData; font.pixelSize: 11; onClicked: root.actionRequested(modelData) } }
    }
}
