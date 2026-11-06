import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog

    property var appPalette: ({})
    property var completionSnapshot: ({ state: "idle" })
    property string transactionKey: ""
    property string backendSessionId: ""
    property real dialogWidth: 1180
    property real dialogHeight: 650

    signal continueRequested(string transactionId)
    signal dismissed(string transactionKey, string backendSessionId)

    modal: true
    title: "Z-probe result"
    width: Math.min(560, dialogWidth - 40)
    height: Math.min(480, dialogHeight - 32)
    x: Math.round((dialogWidth - width) / 2)
    y: Math.round((dialogHeight - height) / 2)
    standardButtons: Dialog.NoButton
    closePolicy: Popup.CloseOnEscape
    background: Rectangle {
        color: dialog.appPalette.surface
        radius: 12
        border.color: dialog.appPalette.divider
        border.width: 1
    }

    function formatMillimeters(value) {
        if (value === null || value === undefined || value === "")
            return "—"
        const number = Number(value)
        return isNaN(number) ? "—" : number.toFixed(3) + " mm"
    }

    onClosed: dismissed(dialog.transactionKey, dialog.backendSessionId)

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 12

        Label {
            Layout.fillWidth: true
            text: dialog.completionSnapshot.state === "complete" ? "Work surface set to Z0"
                : dialog.completionSnapshot.state === "lowering" ? "Moving to the work surface"
                : dialog.completionSnapshot.state === "failed" ? "Z-probe continuation failed"
                : "Probe measurement confirmed"
            color: dialog.completionSnapshot.state === "failed" ? dialog.appPalette.danger : dialog.appPalette.text
            font.pixelSize: 18
            font.weight: Font.DemiBold
        }

        Label {
            visible: dialog.completionSnapshot.state === "waiting-removal"
            Layout.fillWidth: true
            text: "Remove the touch puck and probe clip from the workpiece, then continue. Pine will move Z to work Z0; the spindle stays off and X/Y stay unchanged."
            color: dialog.appPalette.warning
            wrapMode: Text.Wrap
        }

        Label {
            visible: dialog.completionSnapshot.state === "lowering"
            Layout.fillWidth: true
            text: "The guarded Z descent is in progress. The spindle stays off and X/Y stay unchanged."
            color: dialog.appPalette.muted
            wrapMode: Text.Wrap
        }

        Label {
            visible: dialog.completionSnapshot.state === "complete"
            Layout.fillWidth: true
            text: "The backend confirmed work Z0. The spindle stayed off and X/Y were unchanged."
            color: dialog.appPalette.success
            wrapMode: Text.Wrap
        }

        Label {
            visible: dialog.completionSnapshot.state === "failed"
            Layout.fillWidth: true
            text: "Review the reported error and current machine state before taking another action."
            color: dialog.appPalette.danger
            wrapMode: Text.Wrap
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: 14
            rowSpacing: 8

            Label { text: "Puck thickness"; color: dialog.appPalette.muted }
            Label { text: dialog.formatMillimeters(dialog.completionSnapshot.plate_thickness); color: dialog.appPalette.text }
            Label { text: "Measured machine Z"; color: dialog.appPalette.muted }
            Label { text: dialog.formatMillimeters(dialog.completionSnapshot.measured_machine_z); color: dialog.appPalette.text }
            Label { text: "Target work Z"; color: dialog.appPalette.muted }
            Label { text: dialog.formatMillimeters(dialog.completionSnapshot.target_work_z); color: dialog.appPalette.text }
            Label { text: "Current work Z"; color: dialog.appPalette.muted }
            Label { text: dialog.formatMillimeters(dialog.completionSnapshot.current_work_z); color: dialog.appPalette.text }
        }

        Label {
            visible: Boolean(dialog.completionSnapshot.message)
            Layout.fillWidth: true
            text: String(dialog.completionSnapshot.message || "")
            color: dialog.completionSnapshot.state === "failed" ? dialog.appPalette.danger : dialog.appPalette.muted
            wrapMode: Text.Wrap
        }

        Item { Layout.fillHeight: true }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            Button {
                text: "Close"
                onClicked: dialog.close()
                contentItem: Text {
                    text: "Close"
                    color: dialog.appPalette.text
                    font.pixelSize: 13
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    radius: 9
                    color: parent.down ? dialog.appPalette.elevated : dialog.appPalette.raised
                    border.color: dialog.appPalette.divider
                    border.width: 1
                }
            }
            Button {
                visible: dialog.completionSnapshot.state === "waiting-removal"
                text: "Continue to work Z0"
                padding: 12
                onClicked: dialog.continueRequested(String(dialog.completionSnapshot.transaction_id || ""))
                contentItem: Text {
                    text: "Continue to work Z0"
                    color: "white"
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    radius: 9
                    color: parent.down ? dialog.appPalette.accentHover : dialog.appPalette.accent
                }
            }
        }
    }
}
