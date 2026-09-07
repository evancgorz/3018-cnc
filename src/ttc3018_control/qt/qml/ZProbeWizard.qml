import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    signal continueToCommissioning()
    property var appPalette: ({ surface: "#22252B", raised: "#2B2F36", divider: "#3A3F48", text: "#F2F4F7", muted: "#A8AFBA", subtle: "#737B87", warning: "#F5B942", accent: "#168BFF", danger: "#FF6B6B" })
    readonly property string inputState: appViewModel ? appViewModel.z_touch_plate_input_state : "idle"
    readonly property bool testRunning: inputState === "awaiting_press" || inputState === "awaiting_release"

    modal: true
    title: "Z-probe input wizard"
    width: Math.min(640, (ApplicationWindow.window ? ApplicationWindow.window.width - 32 : 640))
    height: Math.min(500, (ApplicationWindow.window ? ApplicationWindow.window.contentItem.height - 24 : 500))
    x: Math.round(((ApplicationWindow.window ? ApplicationWindow.window.width : 1500) - width) / 2)
    y: Math.max(12, Math.round(((ApplicationWindow.window ? ApplicationWindow.window.contentItem.height : 674) - height) / 2))
    standardButtons: Dialog.NoButton
    background: Rectangle { color: dialog.appPalette.surface; radius: 12; border.color: dialog.appPalette.divider; border.width: 1 }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 22
        spacing: 14

        Label { text: "Verify the touch plate safely"; color: dialog.appPalette.text; font.pixelSize: 19; font.weight: Font.DemiBold }
        Label {
            Layout.fillWidth: true
            text: "This wizard only watches the electrical probe input. It does not move an axis or start a probe cycle."
            color: dialog.appPalette.muted
            wrapMode: Text.Wrap
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 52
            radius: 8
            color: dialog.appPalette.raised
            border.color: dialog.inputState === "blocked" ? dialog.appPalette.warning : dialog.appPalette.divider
            RowLayout {
                anchors.fill: parent
                anchors.margins: 12
                Label {
                    text: dialog.inputState === "passed" ? "✓" : (dialog.inputState === "blocked" ? "!" : "●")
                    color: dialog.inputState === "passed" ? dialog.appPalette.accent : (dialog.inputState === "blocked" ? dialog.appPalette.warning : dialog.appPalette.muted)
                    font.pixelSize: 20
                }
                Label {
                    Layout.fillWidth: true
                    text: appViewModel ? appViewModel.z_touch_plate_input_message : "Connect to GRBL to begin."
                    color: dialog.appPalette.text
                    wrapMode: Text.Wrap
                }
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: dialog.inputState === "passed" ? 3 : (dialog.inputState === "awaiting_release" ? 2 : (dialog.inputState === "awaiting_press" ? 1 : 0))

            ColumnLayout {
                spacing: 10
                Label { text: "Step 1 — Leave the probe open"; color: dialog.appPalette.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                Label {
                    Layout.fillWidth: true
                    text: "Keep the cutter, clip, and touch plate separated. Pine will first confirm that the probe input is inactive."
                    color: dialog.appPalette.muted
                    wrapMode: Text.Wrap
                }
                Label {
                    visible: dialog.inputState === "blocked"
                    Layout.fillWidth: true
                    text: "If P disappears when the cutter touches the plate, enable ‘Invert probe input polarity in GRBL ($6)’ in Hardware capabilities, save, then retry."
                    color: dialog.appPalette.warning
                    wrapMode: Text.Wrap
                }
                Item { Layout.fillHeight: true }
                Button {
                    Layout.fillWidth: true
                    text: dialog.inputState === "blocked" ? "Retry untouched check" : "Begin no-motion test"
                    enabled: appViewModel && appViewModel.connected
                    onClicked: appViewModel.test_z_touch_plate_input()
                }
            }

            ColumnLayout {
                spacing: 10
                Label { text: "Step 2 — Touch and hold"; color: dialog.appPalette.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                Label {
                    Layout.fillWidth: true
                    text: "Touch the conductive cutter to the touch plate and keep them in contact. Pine is watching for P to activate."
                    color: dialog.appPalette.muted
                    wrapMode: Text.Wrap
                }
                Label { text: "Waiting for contact…"; color: dialog.appPalette.accent; font.weight: Font.DemiBold }
                Item { Layout.fillHeight: true }
            }

            ColumnLayout {
                spacing: 10
                Label { text: "Step 3 — Separate the contacts"; color: dialog.appPalette.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                Label {
                    Layout.fillWidth: true
                    text: "The contact was detected. Move the cutter away from the plate so Pine can verify that the input releases again."
                    color: dialog.appPalette.muted
                    wrapMode: Text.Wrap
                }
                Label { text: "Waiting for release…"; color: dialog.appPalette.accent; font.weight: Font.DemiBold }
                Item { Layout.fillHeight: true }
            }

            ColumnLayout {
                spacing: 10
                Label { text: "Electrical input verified"; color: dialog.appPalette.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                Label {
                    Layout.fillWidth: true
                    text: "Pine observed the complete open → touched → open sequence. The input test is complete. Three supervised probe samples are still required before workpiece probing is enabled."
                    color: dialog.appPalette.muted
                    wrapMode: Text.Wrap
                }
                Item { Layout.fillHeight: true }
                Button { Layout.fillWidth: true; text: "Continue to supervised samples…"; onClicked: dialog.continueToCommissioning() }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Label { visible: dialog.testRunning; text: "Keep this wizard open while completing the sequence."; color: dialog.appPalette.subtle }
            Item { Layout.fillWidth: true }
            Button { text: "Close"; onClicked: dialog.close() }
        }
    }
}
