import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs as PlatformDialogs
import QtQuick.Layouts
import "components"

ApplicationWindow {
    id: window
    width: 1500
    height: 920
    minimumWidth: 1180
    minimumHeight: 720
    visible: startupWindowVisible
    title: "Pine"
    color: window.palette.background

    readonly property var palette: ({
        background: Qt.color("#181A1F"), surface: Qt.color("#22252B"),
        raised: Qt.color("#2B2F36"), hover: Qt.color("#343941"),
        accent: Qt.color("#168BFF"), accentHover: Qt.color("#3B9EFF"),
        text: Qt.color("#F2F4F7"), muted: Qt.color("#A8AFBA"),
        subtle: Qt.color("#737B87"), divider: Qt.color("#3A3F48"),
        warning: Qt.color("#F5B942"), danger: Qt.color("#ED5B5B"),
        success: Qt.color("#40C4D9")
    })

    property int workspace: appViewModel ? appViewModel.initial_workspace : 2
    property string toastText: ""
    property string selectedTransport: "USB serial"
    property bool exitBypass: false
    readonly property real usableContentHeight: height - header.height - footer.height

    readonly property var readinessEntries: [
        { label: "Connection", status: appViewModel ? appViewModel.readiness_connection : "required", action: "Connect", reason: appViewModel ? appViewModel.readiness_reason : "Connect to the controller." },
        { label: "Reference", status: appViewModel ? appViewModel.readiness_reference : "required", action: "Establish reference", reason: "Trust the machine position before guarded motion." },
        { label: "Work zero", status: appViewModel ? appViewModel.readiness_work_zero : "required", action: "Set work zero", reason: "Set the origin on the material." },
        { label: "Job", status: appViewModel ? appViewModel.readiness_job : "required", action: "Create or load job", reason: "Prepare a validated toolpath." },
        { label: "Ready", status: appViewModel ? appViewModel.readiness_ready : "required", action: "Review & run", reason: appViewModel ? appViewModel.readiness_reason : "Complete the readiness steps." }
    ]

    function routeReadinessAction(action) {
        if (action === "Connect") { connectionDialog.open(); return }
        if (action === "Establish reference" || action === "Set work zero") { workspace = 2; return }
        if (action === "Create or load job") { workspace = 0; return }
        workspace = 1
    }

    function routeIssueAction(action) {
        if (action === "Connect" || action === "Reconnect") { connectionDialog.open(); return }
        if (action === "Reload job") { workspace = 0; return }
        if (action === "Open console") { consoleDialog.open(); return }
        workspace = 2
    }

    onClosing: function(closeEvent) {
        if (exitBypass) {
            exitBypass = false
            return
        }
        if (appViewModel && appViewModel.requires_exit_prompt) {
            closeEvent.accepted = false
            exitDialog.open()
        }
    }

    Connections {
        target: appViewModel
        function onToast_requested(message) {
            window.toastText = message
            toastTimer.restart()
        }
        function onConfirmation_requested(token, title, message) {
            actionConfirmDialog.token = token
            actionConfirmDialog.title = title
            actionConfirmDialog.message = message
            actionConfirmDialog.open()
        }
        function onUnreferenced_jog_requested() { unreferencedJogDialog.open() }
        function onClose_requested() { window.exitBypass = true; window.close() }
        function onStep_model_imported(recommendedMode) {
            const index = modeCombo.find(recommendedMode)
            if (index >= 0) modeCombo.currentIndex = index
            if (appViewModel) {
                stockWidthField.text = Number(appViewModel.step_suggested_stock_width).toFixed(3)
                stockHeightField.text = Number(appViewModel.step_suggested_stock_height).toFixed(3)
                stockThicknessField.text = Number(appViewModel.step_suggested_stock_thickness).toFixed(3)
                let orientationIndex = orientationCombo.find(appViewModel.step_default_orientation)
                if (orientationIndex >= 0) orientationCombo.currentIndex = orientationIndex
                let zeroIndex = zeroLocationCombo.find(appViewModel.step_default_zero_location)
                if (zeroIndex >= 0) zeroLocationCombo.currentIndex = zeroIndex
                toolDiameterField.text = Number(appViewModel.step_default_tool_diameter).toString()
                stepPassesField.text = Number(appViewModel.step_default_passes).toString()
                stepMaxStepdownField.text = Number(appViewModel.step_default_max_stepdown).toString()
                stepSafeField.text = Number(appViewModel.step_default_safe_z).toString()
                stepCutField.text = Number(appViewModel.step_default_cut_feed).toString()
                stepPlungeField.text = Number(appViewModel.step_default_plunge_feed).toString()
                stepRpmField.text = Number(appViewModel.step_default_spindle_rpm).toString()
            }
            stepDialog.refreshPreview()
            stepWizardDialog.applySuggestions()
            stepWizardDialog.currentStep = 1
            stepWizardDialog.refreshPreview()
        }
    }

    Dialog {
        id: exitDialog
        modal: true
        title: "Machine is not at reference"
        width: 560
        height: 320
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.usableContentHeight - height) / 2)
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Label { text: "The controller is still away from the trusted reference position."; color: window.palette.text; font.pixelSize: 16; font.weight: Font.DemiBold; wrapMode: Text.Wrap; Layout.fillWidth: true }
            MutedLabel { text: "Returning first raises Z, moves X/Y to virtual zero, then lowers Z to reference. This uses the configured jog speed and is available only while GRBL is Idle." }
            Label { text: appViewModel ? "Current: " + appViewModel.machine_position : ""; color: window.palette.muted; font.family: "Cascadia Mono" }
            Item { Layout.fillHeight: true }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Cancel"; onClicked: exitDialog.close() }
                SecondaryButton { text: "Close without moving"; onClicked: { window.exitBypass = true; exitDialog.close(); window.close() } }
                PrimaryButton { text: "Move to reference, then close"; enabled: appViewModel && appViewModel.can_return_to_reference; onClicked: { appViewModel.return_to_reference_and_close(); exitDialog.close() } }
            }
        }
    }

    Dialog {
        id: unreferencedJogDialog
        modal: true
        title: "Manual positioning acknowledgement"
        width: 510
        height: 270
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.usableContentHeight - height) / 2)
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Label { text: "The virtual machine reference has not been established."; color: window.palette.text; font.pixelSize: 16; font.weight: Font.DemiBold }
            MutedLabel { text: "Unreferenced jogs are allowed only after you confirm that you are watching the machine, moving slowly, and will stop before a physical limit. Software envelope checks are inactive until a reference is saved." }
            Item { Layout.fillHeight: true }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Cancel"; onClicked: unreferencedJogDialog.close() }
                PrimaryButton { text: "I will jog carefully"; onClicked: { appViewModel.acknowledge_unreferenced_jog(); unreferencedJogDialog.close() } }
            }
        }
    }

    Timer {
        id: toastTimer
        interval: 4200
        onTriggered: window.toastText = ""
    }

    Dialog {
        id: actionConfirmDialog
        property string token: ""
        property string message: ""
        modal: true
        title: "Confirm action"
        width: 560
        height: 280
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.usableContentHeight - height) / 2)
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 22
            spacing: 14
            Label { text: actionConfirmDialog.message; color: window.palette.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Item { Layout.fillHeight: true }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Cancel"; onClicked: { appViewModel.reject_pending_action(); actionConfirmDialog.close() } }
                PrimaryButton { text: "Confirm"; onClicked: { appViewModel.confirm_pending_action(actionConfirmDialog.token); actionConfirmDialog.close() } }
            }
        }
    }

    Dialog {
        id: connectionDialog
        modal: true
        title: "Connect to controller"
        width: 460
        height: 360
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.usableContentHeight - height) / 2)
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 22
            spacing: 12
            Label { text: "Choose how Pine should reach GRBL."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { text: "Transport"; color: window.palette.subtle; font.pixelSize: 11 }
            ComboBox { id: transportCombo; Layout.fillWidth: true; model: ["USB serial", "Wi-Fi TCP"]; currentIndex: appViewModel && appViewModel.preferred_transport === "Wi-Fi TCP" ? 1 : 0; onActivated: window.selectedTransport = currentText }

            ColumnLayout {
                visible: transportCombo.currentText === "USB serial"
                Layout.fillWidth: true
                spacing: 7
                Label { text: "Serial port"; color: window.palette.subtle; font.pixelSize: 11 }
                RowLayout {
                    Layout.fillWidth: true
                    ComboBox { id: portCombo; Layout.fillWidth: true; model: appViewModel ? appViewModel.ports : []; currentIndex: 0 }
                    SecondaryButton { text: "Refresh"; onClicked: appViewModel.refresh_ports() }
                }
            }

            ColumnLayout {
                visible: transportCombo.currentText === "Wi-Fi TCP"
                Layout.fillWidth: true
                spacing: 7
                Label { text: "Controller address"; color: window.palette.subtle; font.pixelSize: 11 }
                RowLayout {
                    Layout.fillWidth: true
                    Field { id: wifiHostField; Layout.fillWidth: true; text: appViewModel ? appViewModel.saved_wifi_host : "192.168.4.1"; placeholderText: "IP address or host name" }
                    Field { id: wifiPortField; Layout.preferredWidth: 82; text: appViewModel ? String(appViewModel.saved_wifi_port) : "23"; validator: IntValidator { bottom: 1; top: 65535 } }
                }
                MutedLabel { text: "You can remove USB and connect over the controller's Wi-Fi TCP endpoint." }
            }

            Item { Layout.fillHeight: true }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Cancel"; onClicked: connectionDialog.close() }
                PrimaryButton {
                    text: "Connect"
                    enabled: appViewModel && (transportCombo.currentText === "USB serial" ? portCombo.currentText.length > 0 : wifiHostField.text.trim().length > 0)
                    onClicked: {
                        if (transportCombo.currentText === "USB serial") appViewModel.connect_to_usb(portCombo.currentText)
                        else appViewModel.connect_to_wifi(wifiHostField.text, Number(wifiPortField.text))
                        connectionDialog.close()
                    }
                }
            }
        }
    }

    MachineSetupDialog {
        id: machineSetupDialog
        appPalette: window.palette
    }

    onWorkspaceChanged: if (appViewModel) appViewModel.save_workspace(workspace)

    CommissioningDialog {
        id: commissioningDialog
        appPalette: window.palette
    }

    Dialog {
        id: engravingDialog
        modal: true
        property bool plaqueMode: false
        title: plaqueMode ? "Plaque builder" : "Text engraving"
        width: Math.min(1120, window.width - 48)
        height: Math.min(720, window.usableContentHeight - 24)
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.usableContentHeight - height) / 2)
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }
        function refreshPreview() {
            if (!appViewModel) return
            if (plaqueMode) appViewModel.request_preview_plaque(titleField.text, subtitleField.text, subtitleCheck.checked, titleFontCombo.currentText, subtitleFontCombo.currentText, Number(titleHeightField.text), Number(subtitleHeightField.text), Number(widthField.text), Number(plaqueHeightField.text), Number(marginField.text), borderCombo.currentText, Number(plaqueDepthField.text), Number(plaqueSafeField.text), Number(plaqueCutField.text), Number(plaquePlungeField.text), Number(plaqueRpmField.text))
            else appViewModel.request_preview_text(textField.text, fontCombo.currentText, Number(heightField.text), Number(depthField.text), Number(safeField.text), Number(cutField.text), Number(plungeField.text), Number(letterSpacingField.text), Number(lineSpacingField.text), alignmentCombo.currentText, Number(rpmField.text))
        }
        onOpened: refreshPreview()
        onClosed: if (appViewModel) appViewModel.request_preview_text("", "Simple", 8, -0.3, 3, 300, 100, 0.18, 1.4, "Left", 0)
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 20; spacing: 10
            Label { text: "Create a centerline engraving or a bordered plaque from the bundled stroke fonts."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            RowLayout { Layout.fillWidth: true; Layout.fillHeight: true; spacing: 16
                ColumnLayout { Layout.preferredWidth: 430; Layout.minimumWidth: 390; Layout.fillHeight: true; spacing: 10
                    RowLayout { Layout.fillWidth: true
                        Label { text: "Design"; color: window.palette.muted }
                        ComboBox { id: engravingModeCombo; Layout.fillWidth: true; model: ["Plain text", "Plaque"]; currentIndex: engravingDialog.plaqueMode ? 1 : 0; onActivated: { engravingDialog.plaqueMode = currentIndex === 1; engravingDialog.refreshPreview() } }
                    }
                    ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: availableWidth
                        ColumnLayout { width: parent.width; spacing: 9
                    ColumnLayout { visible: !engravingDialog.plaqueMode; Layout.fillWidth: true; spacing: 8
                        Label { text: "Text"; color: window.palette.subtle; font.pixelSize: 11 }
                        Field { id: textField; Layout.fillWidth: true; text: "PINE"; onTextChanged: engravingDialog.refreshPreview() }
                        GridLayout { Layout.fillWidth: true; columns: 2; columnSpacing: 12; rowSpacing: 8
                            Label { text: "Font"; color: window.palette.muted }
                            ComboBox { id: fontCombo; Layout.fillWidth: true; model: appViewModel ? appViewModel.fonts : ["Simple"]; onActivated: engravingDialog.refreshPreview() }
                            Label { text: "Height (mm)"; color: window.palette.muted }
                            Field { id: heightField; Layout.fillWidth: true; text: "8"; validator: DoubleValidator { bottom: 0.5; top: 100 }
                                onTextChanged: engravingDialog.refreshPreview() }
                            Label { text: "Letter spacing"; color: window.palette.muted }
                            Field { id: letterSpacingField; Layout.fillWidth: true; text: "0.18"; validator: DoubleValidator { bottom: 0; top: 2 }
                                onTextChanged: engravingDialog.refreshPreview() }
                            Label { text: "Line spacing"; color: window.palette.muted }
                            Field { id: lineSpacingField; Layout.fillWidth: true; text: "1.4"; validator: DoubleValidator { bottom: 1; top: 3 }
                                onTextChanged: engravingDialog.refreshPreview() }
                            Label { text: "Alignment"; color: window.palette.muted }
                            ComboBox { id: alignmentCombo; Layout.fillWidth: true; model: ["Left", "Center", "Right"]; onActivated: engravingDialog.refreshPreview() }
                        }
                    }
                    ColumnLayout { visible: engravingDialog.plaqueMode; Layout.fillWidth: true; spacing: 8
                        GridLayout { Layout.fillWidth: true; columns: 2; columnSpacing: 12; rowSpacing: 7
                            Label { text: "Title"; color: window.palette.muted }
                            Field { id: titleField; Layout.fillWidth: true; text: "Welcome"; onTextChanged: engravingDialog.refreshPreview() }
                            Label { text: "Title font"; color: window.palette.muted }
                            ComboBox { id: titleFontCombo; Layout.fillWidth: true; model: appViewModel ? appViewModel.fonts : ["Simple"]; onActivated: engravingDialog.refreshPreview() }
                            Label { text: "Title height (mm)"; color: window.palette.muted }
                            Field { id: titleHeightField; Layout.fillWidth: true; text: "10"; validator: DoubleValidator { bottom: 0.5; top: 100 }
                                onTextChanged: engravingDialog.refreshPreview() }
                            Label { text: "Subtitle"; color: window.palette.muted }
                            Field { id: subtitleField; Layout.fillWidth: true; text: ""; onTextChanged: engravingDialog.refreshPreview() }
                            Label { text: "Enable subtitle"; color: window.palette.muted }
                            ModernCheckBox { id: subtitleCheck; palette: window.palette; checked: true; onCheckedChanged: engravingDialog.refreshPreview() }
                            Label { text: "Subtitle font"; color: window.palette.muted }
                            ComboBox { id: subtitleFontCombo; Layout.fillWidth: true; model: appViewModel ? appViewModel.fonts : ["Simple"]; onActivated: engravingDialog.refreshPreview() }
                            Label { text: "Subtitle height (mm)"; color: window.palette.muted }
                            Field { id: subtitleHeightField; Layout.fillWidth: true; text: "5"; validator: DoubleValidator { bottom: 0.5; top: 100 }
                                onTextChanged: engravingDialog.refreshPreview() }
                            Label { text: "Plaque width × height (mm)"; color: window.palette.muted }
                            RowLayout { Layout.fillWidth: true
                                Field { id: widthField; Layout.fillWidth: true; text: "100"; validator: DoubleValidator { bottom: 10; top: 300 }
                                    onTextChanged: engravingDialog.refreshPreview() }
                                Field { id: plaqueHeightField; Layout.fillWidth: true; text: "50"; validator: DoubleValidator { bottom: 10; top: 180 }
                                    onTextChanged: engravingDialog.refreshPreview() }
                            }
                            Label { text: "Inner margin (mm)"; color: window.palette.muted }
                            Field { id: marginField; Layout.fillWidth: true; text: "5"; validator: DoubleValidator { bottom: 1; top: 80 }
                                onTextChanged: engravingDialog.refreshPreview() }
                            Label { text: "Border"; color: window.palette.muted }
                            ComboBox { id: borderCombo; Layout.fillWidth: true; model: appViewModel ? appViewModel.borders : ["Rectangle"]; onActivated: engravingDialog.refreshPreview() }
                        }
                    }
                    Divider {}
                    GridLayout { Layout.fillWidth: true; columns: 2; columnSpacing: 12; rowSpacing: 8
                        Label { text: "Depth (mm)"; color: window.palette.muted }
                        Field { id: depthField; visible: !engravingDialog.plaqueMode; Layout.fillWidth: true; text: "-0.3"; validator: DoubleValidator { bottom: -20; top: -0.001 }
                            onTextChanged: engravingDialog.refreshPreview() }
                        Field { id: plaqueDepthField; visible: engravingDialog.plaqueMode; Layout.fillWidth: true; text: "-0.3"; validator: DoubleValidator { bottom: -20; top: -0.001 }
                            onTextChanged: engravingDialog.refreshPreview() }
                        Label { text: "Safe Z (mm)"; color: window.palette.muted }
                        Field { id: safeField; visible: !engravingDialog.plaqueMode; Layout.fillWidth: true; text: "3"; validator: DoubleValidator { bottom: 0.1; top: 100 }
                            onTextChanged: engravingDialog.refreshPreview() }
                        Field { id: plaqueSafeField; visible: engravingDialog.plaqueMode; Layout.fillWidth: true; text: "3"; validator: DoubleValidator { bottom: 0.1; top: 100 }
                            onTextChanged: engravingDialog.refreshPreview() }
                        Label { text: "Cut feed (mm/min)"; color: window.palette.muted }
                        Field { id: cutField; visible: !engravingDialog.plaqueMode; Layout.fillWidth: true; text: "300"; validator: DoubleValidator { bottom: 1; top: 3000 }
                            onTextChanged: engravingDialog.refreshPreview() }
                        Field { id: plaqueCutField; visible: engravingDialog.plaqueMode; Layout.fillWidth: true; text: "300"; validator: DoubleValidator { bottom: 1; top: 3000 }
                            onTextChanged: engravingDialog.refreshPreview() }
                        Label { text: "Plunge feed (mm/min)"; color: window.palette.muted }
                        Field { id: plungeField; visible: !engravingDialog.plaqueMode; Layout.fillWidth: true; text: "100"; validator: DoubleValidator { bottom: 1; top: 1000 }
                            onTextChanged: engravingDialog.refreshPreview() }
                        Field { id: plaquePlungeField; visible: engravingDialog.plaqueMode; Layout.fillWidth: true; text: "100"; validator: DoubleValidator { bottom: 1; top: 1000 }
                            onTextChanged: engravingDialog.refreshPreview() }
                        Label { text: "Spindle RPM (0 = off)"; color: window.palette.muted }
                        Field { id: rpmField; visible: !engravingDialog.plaqueMode; Layout.fillWidth: true; text: "0"; validator: IntValidator { bottom: 0; top: 24000 }
                            onTextChanged: engravingDialog.refreshPreview() }
                        Field { id: plaqueRpmField; visible: engravingDialog.plaqueMode; Layout.fillWidth: true; text: "0"; validator: IntValidator { bottom: 0; top: 24000 }
                            onTextChanged: engravingDialog.refreshPreview() }
                    }
                        }
                    }
                }
                ColumnLayout { Layout.fillWidth: true; Layout.fillHeight: true; spacing: 8
                    RowLayout { Layout.fillWidth: true
                        SectionTitle { text: "Live preview"; Layout.fillWidth: true }
                        Label { text: engravingDialog.plaqueMode ? "Plaque" : "Text"; color: window.palette.subtle; font.pixelSize: 11 }
                    }
                    ToolpathCanvas { Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 360; modeLabel: engravingDialog.plaqueMode ? "PLAQUE" : "ENGRAVING" }
                    Label { text: appViewModel ? appViewModel.preview_summary : ""; color: window.palette.accent; font.weight: Font.DemiBold; Layout.fillWidth: true; wrapMode: Text.Wrap }
                }
            }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Cancel"; onClicked: engravingDialog.close() }
                PrimaryButton { text: "Generate and load"; onClicked: {
                    if (engravingDialog.plaqueMode) appViewModel.create_plaque(titleField.text, subtitleField.text, subtitleCheck.checked, titleFontCombo.currentText, subtitleFontCombo.currentText, Number(titleHeightField.text), Number(subtitleHeightField.text), Number(widthField.text), Number(plaqueHeightField.text), Number(marginField.text), borderCombo.currentText, Number(plaqueDepthField.text), Number(plaqueSafeField.text), Number(plaqueCutField.text), Number(plaquePlungeField.text), Number(plaqueRpmField.text))
                    else appViewModel.create_text(textField.text, fontCombo.currentText, Number(heightField.text), Number(depthField.text), Number(safeField.text), Number(cutField.text), Number(plungeField.text), Number(letterSpacingField.text), Number(lineSpacingField.text), alignmentCombo.currentText, Number(rpmField.text))
                    engravingDialog.close(); window.workspace = 1
                } }
            }
        }
    }

    Dialog {
        id: wifiSetupDialog
        modal: true
        title: "Configure controller Wi-Fi"
        width: 560
        height: 370
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.usableContentHeight - height) / 2)
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Label { text: "Send station-mode settings to the controller over USB."; color: window.palette.text; font.pixelSize: 16; font.weight: Font.DemiBold }
            Label { text: "The controller will restart after the transaction. Use a 2.4 GHz network; credentials are never saved by this app."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { text: "Network name (SSID)"; color: window.palette.subtle; font.pixelSize: 11 }
            Field { id: wifiSsidField; Layout.fillWidth: true }
            Label { text: "Wi-Fi password"; color: window.palette.subtle; font.pixelSize: 11 }
            Field { id: wifiPasswordField; Layout.fillWidth: true; echoMode: TextInput.Password }
            Item { Layout.fillHeight: true }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Cancel"; onClicked: wifiSetupDialog.close() }
                PrimaryButton { text: "Configure"; enabled: appViewModel && appViewModel.connected; onClicked: { appViewModel.configure_wifi(wifiSsidField.text, wifiPasswordField.text); wifiPasswordField.text = ""; wifiSetupDialog.close() } }
            }
        }
    }

    Dialog {
        id: profileDialog
        modal: true
        title: "Machine profile"
        width: 480
        height: 470
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.usableContentHeight - height) / 2)
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 20; spacing: 10
            Label { text: "Enter measured usable travel. These values protect the virtual envelope."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { text: "Machine name"; color: window.palette.subtle; font.pixelSize: 11 }
            Field { id: profileNameField; Layout.fillWidth: true; text: appViewModel ? appViewModel.profile_name : "Two Trees TTC 3018" }
            GridLayout { Layout.fillWidth: true; columns: 2; columnSpacing: 12; rowSpacing: 8
                Label { text: "X travel (mm)"; color: window.palette.muted }
                Field { id: profileXField; Layout.fillWidth: true; text: appViewModel ? appViewModel.profile_x.toFixed(2) : "300"; validator: DoubleValidator { bottom: 0.001; top: 1000 } }
                Label { text: "Y travel (mm)"; color: window.palette.muted }
                Field { id: profileYField; Layout.fillWidth: true; text: appViewModel ? appViewModel.profile_y.toFixed(2) : "180"; validator: DoubleValidator { bottom: 0.001; top: 1000 } }
                Label { text: "Z travel (mm)"; color: window.palette.muted }
                Field { id: profileZField; Layout.fillWidth: true; text: appViewModel ? appViewModel.profile_z.toFixed(2) : "45"; validator: DoubleValidator { bottom: 0.001; top: 1000 } }
                Label { text: "Safe Z (mm)"; color: window.palette.muted }
                Field { id: profileSafeField; Layout.fillWidth: true; text: appViewModel ? appViewModel.profile_safe_z.toFixed(2) : "3"; validator: DoubleValidator { bottom: 0; top: 1000 } }
            }
            Label { text: appViewModel ? appViewModel.profile_summary : ""; color: window.palette.subtle; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Item { Layout.fillHeight: true }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Cancel"; onClicked: profileDialog.close() }
                PrimaryButton { text: "Save profile"; onClicked: { appViewModel.save_profile(profileNameField.text, Number(profileXField.text), Number(profileYField.text), Number(profileZField.text), Number(profileSafeField.text)); profileDialog.close() } }
            }
        }
    }

    Dialog {
        id: consoleDialog
        modal: true
        title: "Controller console"
        width: 820
        height: 520
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.usableContentHeight - height) / 2)
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 16; spacing: 10
            Label { text: "Read-only transport and GRBL messages"; color: window.palette.muted }
            Rectangle { Layout.fillWidth: true; Layout.fillHeight: true; color: "#14161A"; radius: 8; border.color: window.palette.divider
                ListView { id: consoleList; anchors.fill: parent; anchors.margins: 10; model: appViewModel ? appViewModel.log_lines : []; clip: true; delegate: Label { width: consoleList.width; text: modelData; color: window.palette.muted; font.family: "Cascadia Mono"; font.pixelSize: 11; wrapMode: Text.NoWrap }
                    onCountChanged: if (count > 0) positionViewAtEnd()
                }
            }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Close"; onClicked: consoleDialog.close() }
            }
        }
    }

    Dialog {
        id: stepWizardDialog
        property int currentStep: 0
        modal: true
        title: "Guided STEP setup · " + (currentStep + 1) + " of 4"
        width: 1080
        height: Math.min(740, window.usableContentHeight - 24)
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.usableContentHeight - height) / 2)
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 14; border.color: window.palette.divider; border.width: 1 }

        function loadDefaults() {
            if (!appViewModel) return
            let index = wizardOrientationCombo.find(appViewModel.step_default_orientation)
            if (index >= 0) wizardOrientationCombo.currentIndex = index
            index = wizardZeroCombo.find(appViewModel.step_default_zero_location)
            if (index >= 0) wizardZeroCombo.currentIndex = index
            wizardToolField.text = Number(appViewModel.step_default_tool_diameter).toString()
            wizardPassesField.text = Number(appViewModel.step_default_passes).toString()
            wizardStepdownField.text = Number(appViewModel.step_default_max_stepdown).toString()
            wizardSafeField.text = Number(appViewModel.step_default_safe_z).toString()
            wizardCutField.text = Number(appViewModel.step_default_cut_feed).toString()
            wizardPlungeField.text = Number(appViewModel.step_default_plunge_feed).toString()
            wizardRpmField.text = Number(appViewModel.step_default_spindle_rpm).toString()
            wizardBreakthroughField.text = Number(appViewModel.step_default_breakthrough).toString()
            wizardTabsField.text = Number(appViewModel.step_default_tab_count).toString()
            wizardTabWidthField.text = Number(appViewModel.step_default_tab_width).toString()
            wizardTabHeightField.text = Number(appViewModel.step_default_tab_height).toString()
        }
        function applySuggestions() {
            if (!appViewModel || !appViewModel.step_loaded) return
            const rotated = wizardOrientationCombo.currentText === "Top (YX)"
            const modelWidth = rotated ? Number(appViewModel.step_model_height) : Number(appViewModel.step_model_width)
            const modelHeight = rotated ? Number(appViewModel.step_model_width) : Number(appViewModel.step_model_height)
            const toolDiameter = Number(wizardToolField.text || appViewModel.step_default_tool_diameter)
            wizardStockWidthField.text = (modelWidth + toolDiameter).toFixed(3)
            wizardStockHeightField.text = (modelHeight + toolDiameter).toFixed(3)
            wizardThicknessField.text = Number(appViewModel.step_suggested_stock_thickness).toFixed(3)
            const safeTabHeight = Math.min(Number(appViewModel.step_default_tab_height), Math.max(0.1, Number(appViewModel.step_suggested_stock_thickness) * 0.4))
            wizardTabHeightField.text = safeTabHeight.toFixed(3)
        }
        function refreshPreview() { wizardPreviewTimer.restart() }
        function previewNow() {
            if (!appViewModel || !appViewModel.step_loaded) return
            appViewModel.preview_step(
                "Automatic part", wizardOrientationCombo.currentText,
                Number(wizardStockWidthField.text), Number(wizardStockHeightField.text),
                wizardZeroCombo.currentText, Number(wizardToolField.text), -0.5,
                Number(wizardPassesField.text), Number(wizardThicknessField.text),
                Number(wizardBreakthroughField.text), Number(wizardTabsField.text),
                Number(wizardTabWidthField.text), Number(wizardTabHeightField.text),
                Number(wizardSafeField.text), Number(wizardCutField.text),
                Number(wizardPlungeField.text), Number(wizardRpmField.text),
                Number(wizardStepdownField.text)
            )
        }
        function saveDefaults() {
            if (!appViewModel) return
            appViewModel.save_step_prepare_defaults(
                wizardOrientationCombo.currentText, wizardZeroCombo.currentText,
                Number(wizardToolField.text), Number(wizardPassesField.text),
                Number(wizardStepdownField.text), Number(wizardSafeField.text),
                Number(wizardCutField.text), Number(wizardPlungeField.text),
                Number(wizardRpmField.text), Number(wizardBreakthroughField.text),
                Number(wizardTabsField.text), Number(wizardTabWidthField.text),
                Number(wizardTabHeightField.text)
            )
        }
        function generateAndLoad() {
            saveDefaults()
            previewNow()
            if (!appViewModel || !appViewModel.step_preview_valid) return
            appViewModel.create_step(
                "Automatic part", wizardOrientationCombo.currentText,
                Number(wizardStockWidthField.text), Number(wizardStockHeightField.text),
                wizardZeroCombo.currentText, Number(wizardToolField.text), -0.5,
                Number(wizardPassesField.text), Number(wizardThicknessField.text),
                Number(wizardBreakthroughField.text), Number(wizardTabsField.text),
                Number(wizardTabWidthField.text), Number(wizardTabHeightField.text),
                Number(wizardSafeField.text), Number(wizardCutField.text),
                Number(wizardPlungeField.text), Number(wizardRpmField.text),
                Number(wizardStepdownField.text)
            )
            close()
            window.workspace = 1
        }
        onOpened: {
            loadDefaults()
            currentStep = appViewModel && appViewModel.step_loaded ? 1 : 0
            if (appViewModel && appViewModel.step_loaded) applySuggestions()
            refreshPreview()
        }
        Timer { id: wizardPreviewTimer; interval: 300; repeat: false; onTriggered: stepWizardDialog.previewNow() }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Repeater {
                    model: ["Import", "Understand", "Set up", "Review"]
                    delegate: Rectangle {
                        Layout.fillWidth: true
                        height: 42
                        radius: 10
                        color: index === stepWizardDialog.currentStep ? Qt.rgba(window.palette.accent.r, window.palette.accent.g, window.palette.accent.b, 0.20) : index < stepWizardDialog.currentStep ? Qt.rgba(window.palette.success.r, window.palette.success.g, window.palette.success.b, 0.12) : window.palette.raised
                        border.color: index === stepWizardDialog.currentStep ? window.palette.accent : index < stepWizardDialog.currentStep ? window.palette.success : window.palette.divider
                        Label { anchors.centerIn: parent; text: (index + 1) + ". " + modelData; color: index <= stepWizardDialog.currentStep ? window.palette.text : window.palette.muted; font.weight: index === stepWizardDialog.currentStep ? Font.DemiBold : Font.Normal }
                    }
                }
            }

            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: stepWizardDialog.currentStep

                Item {
                    RowLayout { anchors.fill: parent; spacing: 14
                        Panel { Layout.preferredWidth: 390; Layout.fillHeight: true
                            ColumnLayout { anchors.fill: parent; anchors.margins: 20; spacing: 14
                                SectionTitle { text: "Choose the STEP model" }
                                Label { text: "The importer finds a usable machining face, identifies recesses and raised bosses, and detects accessible ramp surfaces."; color: window.palette.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                MutedLabel { text: "Nothing moves during import or preview. The generated program still passes the normal parser, stock simulation, and machine-envelope checks." }
                                Divider {}
                                BusyButton { Layout.fillWidth: true; palette: window.palette; idleText: "Import STEP file…"; busy: appViewModel && appViewModel.step_importing; actionEnabled: !appViewModel || !appViewModel.step_importing; onClicked: stepFileDialog.open() }
                                Label { text: appViewModel ? appViewModel.step_source : "No model selected"; color: window.palette.accent; font.weight: Font.DemiBold; elide: Text.ElideMiddle; Layout.fillWidth: true }
                                Label { text: appViewModel ? appViewModel.step_model_summary : ""; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                Item { Layout.fillHeight: true }
                            }
                        }
                        Panel { Layout.fillWidth: true; Layout.fillHeight: true
                            IsometricCanvas { anchors.fill: parent; anchors.margins: 12; modeLabel: "MODEL" }
                        }
                    }
                }

                Item {
                    RowLayout { anchors.fill: parent; spacing: 14
                        Panel { Layout.preferredWidth: 390; Layout.fillHeight: true
                            ColumnLayout { anchors.fill: parent; anchors.margins: 20; spacing: 13
                                SectionTitle { text: "Automatic machining proposal" }
                                Pill { label: appViewModel ? appViewModel.step_recommended_mode : "Automatic part"; tone: window.palette.accent }
                                Label { text: appViewModel ? appViewModel.step_model_summary : ""; color: window.palette.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                Divider {}
                                MutedLabel { text: "1. Machine detected recesses, raised bosses, or accessible wedge/ramp surfaces." }
                                MutedLabel { text: "2. Retract to safe Z between disconnected regions." }
                                MutedLabel { text: "3. Cut the compensated outer profile last, leaving holding tabs." }
                                MutedLabel { text: "4. Keep all XY cutter motion at or above work X0/Y0." }
                                Item { Layout.fillHeight: true }
                            }
                        }
                        Panel { Layout.fillWidth: true; Layout.fillHeight: true
                            IsometricCanvas { anchors.fill: parent; anchors.margins: 12; modeLabel: "3D MODEL" }
                        }
                    }
                }

                Item {
                    RowLayout { anchors.fill: parent; spacing: 14
                        Panel { Layout.fillWidth: true; Layout.fillHeight: true
                            ScrollView { anchors.fill: parent; anchors.margins: 18; clip: true; contentWidth: availableWidth
                                ColumnLayout { width: parent.width; spacing: 10
                                    SectionTitle { text: "Stock and tool" }
                                    MutedLabel { text: "Stock dimensions are suggested from this model. Confirm the physical thickness—the automatic profile cuts through it plus breakthrough." }
                                    GridLayout { Layout.fillWidth: true; columns: 2; columnSpacing: 12; rowSpacing: 8
                                        Label { text: "Stock width (mm)"; color: window.palette.muted }
                                        Field { id: wizardStockWidthField; Layout.fillWidth: true; text: "33.175"; onTextChanged: stepWizardDialog.refreshPreview() }
                                        Label { text: "Stock height (mm)"; color: window.palette.muted }
                                        Field { id: wizardStockHeightField; Layout.fillWidth: true; text: "18.175"; onTextChanged: stepWizardDialog.refreshPreview() }
                                        Label { text: "Stock thickness (mm)"; color: window.palette.muted }
                                        Field { id: wizardThicknessField; Layout.fillWidth: true; text: "2"; onTextChanged: stepWizardDialog.refreshPreview() }
                                        Label { text: "Tool diameter (mm)"; color: window.palette.muted }
                                        Field { id: wizardToolField; Layout.fillWidth: true; text: "3.175"; onTextChanged: stepWizardDialog.refreshPreview() }
                                        Label { text: "Path rotation"; color: window.palette.muted }
                                        ComboBox { id: wizardOrientationCombo; Layout.fillWidth: true; model: appViewModel ? appViewModel.step_orientations : ["Top (XY)"]; onActivated: { stepWizardDialog.applySuggestions(); stepWizardDialog.refreshPreview() } }
                                        Label { text: "Work zero"; color: window.palette.muted }
                                        ComboBox { id: wizardZeroCombo; Layout.fillWidth: true; model: appViewModel ? appViewModel.step_zero_locations : ["Lower-left"]; onActivated: stepWizardDialog.refreshPreview() }
                                    }
                                    Divider {}
                                    SectionTitle { text: "Through cut and tabs" }
                                    GridLayout { Layout.fillWidth: true; columns: 2; columnSpacing: 12; rowSpacing: 8
                                        Label { text: "Breakthrough (mm)"; color: window.palette.muted }
                                        Field { id: wizardBreakthroughField; Layout.fillWidth: true; text: "0.2"; onTextChanged: stepWizardDialog.refreshPreview() }
                                        Label { text: "Holding tabs"; color: window.palette.muted }
                                        Field { id: wizardTabsField; Layout.fillWidth: true; text: "4"; onTextChanged: stepWizardDialog.refreshPreview() }
                                        Label { text: "Tab width (mm)"; color: window.palette.muted }
                                        Field { id: wizardTabWidthField; Layout.fillWidth: true; text: "4"; onTextChanged: stepWizardDialog.refreshPreview() }
                                        Label { text: "Tab height (mm)"; color: window.palette.muted }
                                        Field { id: wizardTabHeightField; Layout.fillWidth: true; text: "0.8"; onTextChanged: stepWizardDialog.refreshPreview() }
                                    }
                                }
                            }
                        }
                        Panel { Layout.fillWidth: true; Layout.fillHeight: true
                            ScrollView { anchors.fill: parent; anchors.margins: 18; clip: true; contentWidth: availableWidth
                                ColumnLayout { width: parent.width; spacing: 10
                                    SectionTitle { text: "Reusable cutting defaults" }
                                    MutedLabel { text: "These values persist for the next session. Model dimensions and detected geometry do not." }
                                    GridLayout { Layout.fillWidth: true; columns: 2; columnSpacing: 12; rowSpacing: 8
                                        Label { text: "Minimum passes"; color: window.palette.muted }
                                        Field { id: wizardPassesField; Layout.fillWidth: true; text: "2"; onTextChanged: stepWizardDialog.refreshPreview() }
                                        Label { text: "Max stepdown (mm)"; color: window.palette.muted }
                                        Field { id: wizardStepdownField; Layout.fillWidth: true; text: "1"; onTextChanged: stepWizardDialog.refreshPreview() }
                                        Label { text: "Safe Z (mm)"; color: window.palette.muted }
                                        Field { id: wizardSafeField; Layout.fillWidth: true; text: "3"; onTextChanged: stepWizardDialog.refreshPreview() }
                                        Label { text: "Cut feed (mm/min)"; color: window.palette.muted }
                                        Field { id: wizardCutField; Layout.fillWidth: true; text: "300"; onTextChanged: stepWizardDialog.refreshPreview() }
                                        Label { text: "Plunge feed (mm/min)"; color: window.palette.muted }
                                        Field { id: wizardPlungeField; Layout.fillWidth: true; text: "100"; onTextChanged: stepWizardDialog.refreshPreview() }
                                        Label { text: "Spindle RPM (0 = manual/off)"; color: window.palette.muted }
                                        Field { id: wizardRpmField; Layout.fillWidth: true; text: "0"; onTextChanged: stepWizardDialog.refreshPreview() }
                                    }
                                    Divider {}
                                    Label { text: appViewModel ? appViewModel.preview_summary : ""; color: appViewModel && appViewModel.step_preview_valid ? window.palette.success : window.palette.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                }
                            }
                        }
                    }
                }

                Item {
                    RowLayout { anchors.fill: parent; spacing: 14
                        Panel { Layout.fillWidth: true; Layout.fillHeight: true
                            IsometricCanvas { anchors.fill: parent; anchors.margins: 12; modeLabel: "3D TOOLPATH" }
                        }
                        Panel { Layout.preferredWidth: 400; Layout.minimumWidth: 400; Layout.fillHeight: true
                            ScrollView { anchors.fill: parent; anchors.margins: 18; clip: true; contentWidth: availableWidth
                                ColumnLayout { width: parent.width; spacing: 10
                                    SectionTitle { text: "Review the complete proposal" }
                                    Label { text: appViewModel ? appViewModel.preview_summary : ""; color: window.palette.accent; font.weight: Font.DemiBold; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    Divider {}
                                    SectionTitle { text: "Ordered operations" }
                                    Repeater {
                                        model: appViewModel ? appViewModel.step_operations : []
                                        delegate: Rectangle {
                                            Layout.fillWidth: true; implicitHeight: 58; radius: 9; color: window.palette.raised; border.color: window.palette.divider
                                            Column { anchors.fill: parent; anchors.margins: 9; spacing: 3
                                                Label { text: (index + 1) + ". " + modelData.kind; color: window.palette.text; font.weight: Font.DemiBold; width: parent.width; elide: Text.ElideRight }
                                                Label { text: "Target Z " + Number(modelData.targetDepth).toFixed(2) + " mm · " + modelData.strategy; color: window.palette.muted; font.pixelSize: 11; width: parent.width; elide: Text.ElideRight }
                                                Label { visible: modelData.dependsOn.length > 0; text: "Runs after " + modelData.dependsOn; color: window.palette.success; font.pixelSize: 10 }
                                            }
                                        }
                                    }
                                    Divider {}
                                    MutedLabel { text: "Blue paths machine the model. Cyan is the final compensated outer profile. The translucent box is the confirmed physical stock." }
                                }
                            }
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                SecondaryButton { text: "Cancel"; onClicked: stepWizardDialog.close() }
                SecondaryButton { text: "Advanced settings"; onClicked: { stepWizardDialog.close(); stepDialog.open() } }
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Back"; enabled: stepWizardDialog.currentStep > 0; onClicked: stepWizardDialog.currentStep-- }
                PrimaryButton {
                    visible: stepWizardDialog.currentStep < 3
                    text: "Next"
                    enabled: appViewModel && appViewModel.step_loaded && (stepWizardDialog.currentStep !== 2 || appViewModel.step_preview_valid)
                    onClicked: {
                        if (stepWizardDialog.currentStep === 2) {
                            stepWizardDialog.saveDefaults()
                            stepWizardDialog.previewNow()
                        }
                        stepWizardDialog.currentStep++
                    }
                }
                PrimaryButton { visible: stepWizardDialog.currentStep === 3; text: "Generate and load"; enabled: appViewModel && appViewModel.step_preview_valid; onClicked: stepWizardDialog.generateAndLoad() }
            }
        }
    }

    Dialog {
        id: stepDialog
        modal: true
        title: "STEP / 2.5D machining"
        width: 980
        height: Math.min(720, window.usableContentHeight - 24)
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.usableContentHeight - height) / 2)
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }
        function refreshPreview() {
            stepPreviewTimer.restart()
        }
        function previewNow() {
             if (appViewModel) appViewModel.preview_step(modeCombo.currentText, orientationCombo.currentText, Number(stockWidthField.text), Number(stockHeightField.text), zeroLocationCombo.currentText, Number(toolDiameterField.text), Number(stepDepthField.text), Number(stepPassesField.text), Number(stockThicknessField.text), Number(breakthroughField.text), Number(tabCountField.text), Number(tabWidthField.text), Number(tabHeightField.text), Number(stepSafeField.text), Number(stepCutField.text), Number(stepPlungeField.text), Number(stepRpmField.text), Number(stepMaxStepdownField.text))
        }
        Timer { id: stepPreviewTimer; interval: 250; repeat: false; onTriggered: stepDialog.previewNow() }
        onOpened: refreshPreview()
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 20; spacing: 10
            Label { text: "Import a STEP model and generate a bounded 2.5D toolpath from accessible planar faces, pockets, bosses, holes, and ramps."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            RowLayout { Layout.fillWidth: true; spacing: 10
                BusyButton { palette: window.palette; idleText: "Import STEP…"; busy: appViewModel && appViewModel.step_importing; actionEnabled: !appViewModel || !appViewModel.step_importing; onClicked: stepFileDialog.open() }
                Label { text: appViewModel ? appViewModel.step_source : "No STEP model imported"; color: window.palette.text; elide: Text.ElideMiddle; Layout.fillWidth: true }
            }
            Label { text: appViewModel ? appViewModel.step_model_summary : "Import a planar STEP model to begin."; color: window.palette.accent; font.weight: Font.DemiBold; Layout.fillWidth: true }
            RowLayout { Layout.fillWidth: true; spacing: 10
                Label { text: "Machining face"; color: window.palette.muted }
                ComboBox { id: planeCombo; Layout.preferredWidth: 250; model: appViewModel ? appViewModel.step_planes : ["Auto (largest planar face)"]; onActivated: appViewModel.set_step_plane(currentText) }
                Label { text: appViewModel && appViewModel.step_loaded ? "Select a planar face, then use path rotation below if needed." : "Choose a planar face when the CAD model is standing on its side."; color: window.palette.muted; elide: Text.ElideRight; Layout.fillWidth: true }
            }
            RowLayout { Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
                Panel { Layout.fillWidth: true; Layout.fillHeight: true
                    ToolpathCanvas { anchors.fill: parent; anchors.margins: 12; modeLabel: "STEP PREVIEW" }
                }
                Panel { Layout.preferredWidth: 390; Layout.minimumWidth: 390; Layout.maximumWidth: 390; Layout.fillHeight: true
                    ScrollView { anchors.fill: parent; anchors.margins: 14; clip: true; contentWidth: availableWidth
                        ColumnLayout { width: parent.width; spacing: 8
                            SectionTitle { text: "Model and stock" }
                            Label { text: "Machining mode"; color: window.palette.muted; font.pixelSize: 11 }
                            ComboBox { id: modeCombo; Layout.fillWidth: true; model: appViewModel ? appViewModel.step_modes : ["Engraving"]; onActivated: stepDialog.refreshPreview() }
                            Label { text: "Path rotation"; color: window.palette.muted; font.pixelSize: 11 }
                            ComboBox { id: orientationCombo; Layout.fillWidth: true; model: appViewModel ? appViewModel.step_orientations : ["Top (XY)"]; onActivated: stepDialog.refreshPreview() }
                            Label { text: "Work zero"; color: window.palette.muted; font.pixelSize: 11 }
                            ComboBox { id: zeroLocationCombo; Layout.fillWidth: true; model: appViewModel ? appViewModel.step_zero_locations : ["Center"]; currentIndex: 0; onActivated: stepDialog.refreshPreview() }
                            GridLayout { Layout.fillWidth: true; columns: 2; columnSpacing: 10; rowSpacing: 7
                                Label { text: "Stock width (mm)"; color: window.palette.muted }
                                Field { id: stockWidthField; Layout.fillWidth: true; text: "50"; validator: DoubleValidator { bottom: 0.1; top: 1000 }
                                    onTextChanged: stepDialog.refreshPreview() }
                                Label { text: "Stock height (mm)"; color: window.palette.muted }
                                Field { id: stockHeightField; Layout.fillWidth: true; text: "35"; validator: DoubleValidator { bottom: 0.1; top: 1000 }
                                    onTextChanged: stepDialog.refreshPreview() }
                                Label { text: "Tool diameter (mm)"; color: window.palette.muted }
                                Field { id: toolDiameterField; Layout.fillWidth: true; text: "3.175"; validator: DoubleValidator { bottom: 0.1; top: 20 }
                                    onTextChanged: stepDialog.refreshPreview() }
                            }
                            ColumnLayout { Layout.fillWidth: true; spacing: 5; visible: appViewModel && appViewModel.step_operations.length > 0
                                Divider {}
                                SectionTitle { text: "Operation plan" }
                                Repeater {
                                    model: appViewModel ? appViewModel.step_operations : []
                                    delegate: Rectangle {
                                        Layout.fillWidth: true; implicitHeight: modelData.dependsOn ? 49 : 38
                                        radius: 8; color: window.palette.elevated; border.color: window.palette.divider; border.width: 1
                                        Column {
                                            anchors.fill: parent; anchors.margins: 8; spacing: 2
                                            Label { text: (index + 1) + ". " + modelData.kind; color: window.palette.text; font.pixelSize: 11; font.weight: Font.DemiBold; elide: Text.ElideRight; width: parent.width }
                                             Label { text: "Target Z " + Number(modelData.targetDepth).toFixed(2) + " mm" + (modelData.strategy ? " · " + modelData.strategy : "") + (modelData.dependsOn ? " · after " + modelData.dependsOn : ""); color: window.palette.muted; font.pixelSize: 10; elide: Text.ElideRight; width: parent.width }
                                        }
                                    }
                                }
                            }
                             ColumnLayout { Layout.fillWidth: true; spacing: 7; visible: modeCombo.currentText === "Automatic part" || modeCombo.currentText === "Profile cutout" || modeCombo.currentText === "Detected feature"
                                Divider {}
                                 SectionTitle { text: modeCombo.currentText === "Automatic part" ? "Automatic cutout and holding tabs" : modeCombo.currentText === "Profile cutout" ? "Through cut and holding tabs" : "Feature stock reference" }
                                 MutedLabel { text: modeCombo.currentText === "Automatic part" ? "Accessible features or ramps run first. The compensated outer profile runs last and leaves holding tabs." : modeCombo.currentText === "Profile cutout" ? "Inner cutouts run first. The compensated outer profile runs last and leaves tabs so the finished part stays attached to the stock." : "Confirm the physical stock thickness before generating detected through-features."
                                 }
                                GridLayout { Layout.fillWidth: true; columns: 2; columnSpacing: 10; rowSpacing: 7
                                    Label { text: "Stock thickness (mm)"; color: window.palette.muted }
                                    Field { id: stockThicknessField; Layout.fillWidth: true; text: "2.0"; validator: DoubleValidator { bottom: 0.1; top: 20 }
                                        onTextChanged: stepDialog.refreshPreview() }
                                    Label { text: "Breakthrough (mm)"; color: window.palette.muted }
                                    Field { id: breakthroughField; Layout.fillWidth: true; text: "0.2"; validator: DoubleValidator { bottom: 0; top: 2 }
                                        onTextChanged: stepDialog.refreshPreview() }
                                    Label { text: "Outer tab count"; color: window.palette.muted }
                                    Field { id: tabCountField; Layout.fillWidth: true; text: "4"; validator: IntValidator { bottom: 0; top: 12 }
                                        onTextChanged: stepDialog.refreshPreview() }
                                    Label { text: "Tab width (mm)"; color: window.palette.muted }
                                    Field { id: tabWidthField; Layout.fillWidth: true; text: "4.0"; validator: DoubleValidator { bottom: 0.5; top: 20 }
                                        onTextChanged: stepDialog.refreshPreview() }
                                    Label { text: "Tab height (mm)"; color: window.palette.muted }
                                    Field { id: tabHeightField; Layout.fillWidth: true; text: "0.8"; validator: DoubleValidator { bottom: 0.1; top: 19.9 }
                                        onTextChanged: stepDialog.refreshPreview() }
                                }
                            }
                            Divider {}
                            SectionTitle { text: "Cut parameters" }
                            GridLayout { Layout.fillWidth: true; columns: 2; columnSpacing: 10; rowSpacing: 7
                                Label { text: modeCombo.currentText === "Automatic part" ? "Depth (automatic)" : modeCombo.currentText === "Profile cutout" ? "Depth (from stock)" : modeCombo.currentText === "Detected feature" ? "Depth (from STEP feature)" : modeCombo.currentText === "Planar surface" ? "Depth (from STEP surface)" : "Depth (mm)"; color: window.palette.muted }
                                Field { id: stepDepthField; Layout.fillWidth: true; text: "-0.5"; enabled: modeCombo.currentText !== "Automatic part" && modeCombo.currentText !== "Profile cutout" && modeCombo.currentText !== "Detected feature" && modeCombo.currentText !== "Planar surface"; validator: DoubleValidator { bottom: -20; top: -0.001 }
                                    onTextChanged: stepDialog.refreshPreview() }
                                 Label { text: "Depth passes"; color: window.palette.muted }
                                 Field { id: stepPassesField; Layout.fillWidth: true; text: "2"; validator: IntValidator { bottom: 1; top: 100 }
                                     onTextChanged: stepDialog.refreshPreview() }
                                 Label { text: "Max stepdown (mm, 0 = auto)"; color: window.palette.muted }
                                 Field { id: stepMaxStepdownField; Layout.fillWidth: true; text: "0"; validator: DoubleValidator { bottom: 0; top: 20 }
                                     onTextChanged: stepDialog.refreshPreview() }
                                Label { text: "Safe Z (mm)"; color: window.palette.muted }
                                Field { id: stepSafeField; Layout.fillWidth: true; text: "3"; validator: DoubleValidator { bottom: 0.1; top: 100 }
                                    onTextChanged: stepDialog.refreshPreview() }
                                Label { text: "Cut feed (mm/min)"; color: window.palette.muted }
                                Field { id: stepCutField; Layout.fillWidth: true; text: "300"; validator: DoubleValidator { bottom: 1; top: 3000 }
                                    onTextChanged: stepDialog.refreshPreview() }
                                Label { text: "Plunge feed (mm/min)"; color: window.palette.muted }
                                Field { id: stepPlungeField; Layout.fillWidth: true; text: "100"; validator: DoubleValidator { bottom: 1; top: 1000 }
                                    onTextChanged: stepDialog.refreshPreview() }
                                Label { text: "Spindle RPM (0 = off)"; color: window.palette.muted }
                                Field { id: stepRpmField; Layout.fillWidth: true; text: "0"; validator: IntValidator { bottom: 0; top: 24000 }
                                    onTextChanged: stepDialog.refreshPreview() }
                            }
                            MutedLabel { text: "Automatic part machines detected features or ramps first, then cuts the outer profile free. Planar surface follows accessible flat and ramp faces. Detected feature clears inside a recess or around a raised boss." }
                        }
                    }
                }
            }
             Label { text: appViewModel ? appViewModel.preview_summary : ""; color: window.palette.accent; font.weight: Font.DemiBold; Layout.fillWidth: true; wrapMode: Text.Wrap }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Cancel"; onClicked: stepDialog.close() }
                 PrimaryButton { text: "Generate and load"; enabled: appViewModel && appViewModel.step_loaded && !appViewModel.step_importing && appViewModel.step_preview_valid; onClicked: { appViewModel.create_step(modeCombo.currentText, orientationCombo.currentText, Number(stockWidthField.text), Number(stockHeightField.text), zeroLocationCombo.currentText, Number(toolDiameterField.text), Number(stepDepthField.text), Number(stepPassesField.text), Number(stockThicknessField.text), Number(breakthroughField.text), Number(tabCountField.text), Number(tabWidthField.text), Number(tabHeightField.text), Number(stepSafeField.text), Number(stepCutField.text), Number(stepPlungeField.text), Number(stepRpmField.text), Number(stepMaxStepdownField.text)); stepDialog.close(); window.workspace = 1 } }
            }
        }
    }

    PlatformDialogs.FileDialog {
        id: gcodeFileDialog
        title: "Load existing job"
        nameFilters: ["G-code files (*.nc *.gcode *.tap *.cnc *.txt)", "All files (*.*)"]
        onAccepted: appViewModel.load_gcode_file(selectedFile)
    }

    PlatformDialogs.FileDialog {
        id: saveGcodeDialog
        title: "Save validated G-code"
        fileMode: PlatformDialogs.FileDialog.SaveFile
        nameFilters: ["G-code files (*.gcode *.nc)", "All files (*.*)"]
        onAccepted: appViewModel.save_gcode_file(selectedFile)
    }

    PlatformDialogs.FileDialog {
        id: stepFileDialog
        title: "Import planar STEP model"
        nameFilters: ["STEP files (*.step *.stp)", "All files (*.*)"]
        onAccepted: {
            appViewModel.import_step_file(selectedFile)
            stepDialog.refreshPreview()
        }
    }

    component Panel: Rectangle {
        color: window.palette.surface
        radius: 12
        border.color: window.palette.divider
        border.width: 1
    }

    component Divider: Rectangle {
        Layout.fillWidth: true
        height: 1
        color: window.palette.divider
    }

    component SectionTitle: Label {
        font.pixelSize: 14
        font.weight: Font.DemiBold
        color: window.palette.text
    }

    component MutedLabel: Label {
        Layout.fillWidth: true
        color: window.palette.muted
        font.pixelSize: 12
        wrapMode: Text.Wrap
    }

    component Pill: Rectangle {
        required property string label
        required property color tone
        implicitWidth: pillLabel.implicitWidth + 18
        implicitHeight: 26
        radius: 13
        color: Qt.rgba(tone.r, tone.g, tone.b, 0.16)
        border.color: Qt.rgba(tone.r, tone.g, tone.b, 0.42)
        border.width: 1
        Label {
            id: pillLabel
            anchors.centerIn: parent
            text: parent.label
            color: parent.tone
            font.pixelSize: 11
            font.weight: Font.DemiBold
        }
    }

    component PrimaryButton: Button {
        id: control
        property bool dangerous: false
        implicitHeight: 38
        padding: 15
        font.pixelSize: 13
        font.weight: Font.DemiBold
        contentItem: Text {
            text: control.text
            color: window.palette.text
            font: control.font
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 8
            color: control.down ? (control.dangerous ? "#B94343" : "#086FCC")
                                : control.hovered ? (control.dangerous ? "#E26A6A" : window.palette.accentHover)
                                                  : (control.dangerous ? window.palette.danger : window.palette.accent)
        }
    }

    component SecondaryButton: Button {
        id: control
        implicitHeight: 36
        padding: 13
        font.pixelSize: 12
        contentItem: Text {
            text: control.text
            color: control.enabled ? window.palette.text : window.palette.subtle
            font: control.font
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 8
            color: control.down ? "#20242A" : control.hovered ? window.palette.hover : window.palette.raised
            border.width: 1
            border.color: control.enabled ? window.palette.divider : "#30343A"
        }
    }

    component JogArrowButton: Button {
        id: jogControl
        property string glyph: ""
        property bool fine: false
        padding: 3
        font.pixelSize: fine ? 15 : 13
        font.weight: Font.DemiBold
        contentItem: Text {
            text: jogControl.glyph
            color: jogControl.enabled ? window.palette.text : window.palette.subtle
            font: jogControl.font
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            lineHeight: 0.9
            lineHeightMode: Text.ProportionalHeight
        }
        background: Rectangle {
            radius: jogControl.fine ? 8 : 12
            color: jogControl.down ? window.palette.accent : jogControl.hovered ? window.palette.hover : jogControl.fine ? "#252A32" : window.palette.raised
            border.width: 1
            border.color: jogControl.down ? window.palette.accentHover : jogControl.enabled ? window.palette.divider : "#30343A"
        }
    }

    component Field: TextField {
        id: control
        implicitHeight: 36
        color: window.palette.text
        font.pixelSize: 13
        selectByMouse: true
        background: Rectangle {
            radius: 7
            color: "#1C1F24"
            border.color: control.activeFocus ? window.palette.accent : window.palette.divider
            border.width: control.activeFocus ? 2 : 1
        }
    }

    component StatusMetric: Item {
        id: statusMetric
        required property string name
        required property string value
        required property color tone
        implicitWidth: metricLabel.implicitWidth + 22
        implicitHeight: 44
        Column {
            anchors.centerIn: parent
            spacing: 1
            Label { text: statusMetric.name.toUpperCase(); color: window.palette.subtle; font.pixelSize: 9; font.letterSpacing: 1.1 }
            Label { id: metricLabel; text: statusMetric.value; color: statusMetric.tone; font.pixelSize: 12; font.weight: Font.DemiBold }
        }
    }

    header: Rectangle {
        height: 192
        color: window.palette.surface
        border.color: window.palette.divider
        border.width: 1

        ColumnLayout {
            anchors.fill: parent
            anchors.leftMargin: 22
            anchors.rightMargin: 22
            spacing: 2

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 42
                spacing: 16

                Row {
                    spacing: 9
                    Image { width: 28; height: 28; source: "../assets/pine-mark.svg"; fillMode: Image.PreserveAspectFit; anchors.verticalCenter: parent.verticalCenter }
                    Label { text: "PINE"; color: window.palette.text; font.pixelSize: 16; font.weight: Font.Bold; font.letterSpacing: 1.2; anchors.verticalCenter: parent.verticalCenter }
                    Label { text: "CNC STUDIO"; color: window.palette.subtle; font.pixelSize: 10; font.letterSpacing: 1.4; anchors.verticalCenter: parent.verticalCenter }
                }
                Item { Layout.fillWidth: true }
                Pill { label: appViewModel ? appViewModel.connection_text : "Disconnected"; tone: window.palette.warning }
                Pill { label: appViewModel ? appViewModel.grbl_state : "Unknown"; tone: window.palette.muted }
                SecondaryButton { text: appViewModel && appViewModel.connected ? "Disconnect" : "Connect"; onClicked: appViewModel && appViewModel.connected ? appViewModel.disconnect() : connectionDialog.open() }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 48
                spacing: 6

                Repeater {
                    model: ["Prepare", "Preview & Run", "Machine"]
                    delegate: Button {
                        required property int index
                        required property string modelData
                        text: modelData
                        checkable: true
                        checked: window.workspace === index
                        implicitWidth: index === 1 ? 130 : 112
                        implicitHeight: 40
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        onClicked: window.workspace = index
                        contentItem: Text { text: parent.text; color: parent.checked ? window.palette.text : window.palette.muted; font: parent.font; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                        background: Rectangle { radius: 7; color: parent.checked ? Qt.rgba(window.palette.accent.r, window.palette.accent.g, window.palette.accent.b, 0.20) : parent.hovered ? window.palette.hover : "transparent"; border.color: parent.checked ? Qt.rgba(window.palette.accent.r, window.palette.accent.g, window.palette.accent.b, 0.65) : "transparent"; border.width: 1 }
                    }
                }
                Item { Layout.fillWidth: true }
                Label { text: "Pine workspace"; color: window.palette.subtle; font.pixelSize: 11 }
            }

            ReadinessStrip {
                id: readinessStrip
                Layout.fillWidth: true
                Layout.preferredHeight: 42
                palette: window.palette
                entries: window.readinessEntries
                onActivated: window.routeReadinessAction(action)
            }
            OperationBanner {
                Layout.fillWidth: true
                Layout.preferredHeight: 36
                palette: window.palette
                active: appViewModel && appViewModel.operation_active
                name: appViewModel ? appViewModel.operation_name : ""
                phase: appViewModel ? appViewModel.operation_phase : ""
                progress: appViewModel ? appViewModel.operation_progress : 0
            }
        }
    }

    footer: Rectangle {
        height: 54
        color: window.palette.surface
        border.color: window.palette.divider
        border.width: 1
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 22
            anchors.rightMargin: 22
            spacing: 26
            StatusMetric { name: "Machine"; value: appViewModel ? appViewModel.machine_position : "X—  Y—  Z—"; tone: window.palette.text }
            StatusMetric { name: "Work"; value: appViewModel ? appViewModel.work_position : "X—  Y—  Z—"; tone: window.palette.text }
            StatusMetric { name: "Reference"; value: appViewModel ? appViewModel.reference : "Position unknown"; tone: window.palette.warning }
            StatusMetric { name: "Work zero"; value: appViewModel ? appViewModel.work_zero : "Not confirmed"; tone: window.palette.warning }
            Item { Layout.fillWidth: true }
            StatusMetric { name: "Spindle"; value: appViewModel ? appViewModel.spindle : "Off"; tone: window.palette.muted }
        }
    }

    IssueBanner {
        id: issueBanner
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        anchors.topMargin: 198
        z: 20
        palette: window.palette
        active: appViewModel && appViewModel.has_issue
        title: appViewModel ? appViewModel.issue_title : ""
        explanation: appViewModel ? appViewModel.issue_explanation : ""
        actions: appViewModel ? appViewModel.issue_actions : []
        onActionRequested: window.routeIssueAction(action)
    }

    StackLayout {
        anchors.fill: parent
        anchors.margins: 18
        currentIndex: window.workspace

        // Prepare
        Item {
            RowLayout { anchors.fill: parent; spacing: 14
                Panel { Layout.preferredWidth: 210; Layout.minimumWidth: 210; Layout.maximumWidth: 210; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 16; spacing: 10
                        SectionTitle { text: "Create or load" }
                        MutedLabel { text: "Start with an existing G-code file or create a centerline engraving." }
                        Divider {}
                        PrimaryButton { Layout.fillWidth: true; text: "Engraving designer"; onClicked: engravingDialog.open() }
                        PrimaryButton { Layout.fillWidth: true; text: "Guided STEP setup"; onClicked: stepWizardDialog.open() }
                        SecondaryButton { Layout.fillWidth: true; text: "Advanced STEP / 2.5D"; onClicked: stepDialog.open() }
                        Item { Layout.fillHeight: true }
                        Label { text: "Generated jobs are validated before they can run."; color: window.palette.subtle; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
                Panel { Layout.fillWidth: true; Layout.fillHeight: true
                    ToolpathCanvas { anchors.fill: parent; anchors.margins: 18; modeLabel: "PREPARE" }
                }
                Panel { Layout.preferredWidth: 310; Layout.minimumWidth: 310; Layout.maximumWidth: 310; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 16; spacing: 13
                        SectionTitle { text: "Job inspector" }
                        MutedLabel { text: "Select a job source to edit its settings and see the exact centerline toolpath." }
                        Divider {}
                        Label { text: appViewModel ? appViewModel.job_file : "No job selected"; color: window.palette.text; font.pixelSize: 18; font.weight: Font.DemiBold; elide: Text.ElideMiddle; Layout.fillWidth: true }
                    MutedLabel { text: appViewModel ? appViewModel.job_summary : "Load G-code or create an engraving. The canvas remains the single source of visual context."; Layout.fillWidth: true }
                        Item { Layout.fillHeight: true }
                        SecondaryButton { Layout.fillWidth: true; text: "Save validated G-code"; enabled: appViewModel && appViewModel.job_file !== "No G-code loaded"; onClicked: saveGcodeDialog.open() }
                        PrimaryButton { Layout.fillWidth: true; text: "Review & run"; onClicked: window.workspace = 1 }
                    }
                }
            }
        }

        // Preview & Run
        Item {
            RowLayout { anchors.fill: parent; spacing: 14
                Panel { Layout.fillWidth: true; Layout.fillHeight: true
                    ToolpathCanvas { anchors.fill: parent; anchors.margins: 18; modeLabel: "PREVIEW"; showJob: true }
                }
                Panel { Layout.preferredWidth: 355; Layout.minimumWidth: 355; Layout.maximumWidth: 355; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 18; spacing: 13
                        SectionTitle { text: "Preflight" }
                        Pill { label: appViewModel && appViewModel.job_file !== "No G-code loaded" ? "Validated G-code loaded" : "No validated job loaded"; tone: appViewModel && appViewModel.job_file !== "No G-code loaded" ? window.palette.success : window.palette.warning }
                        Divider {}
                        Label { text: appViewModel && appViewModel.job_active ? appViewModel.job_state + " · " + appViewModel.job_progress + "%" : "Ready when verified"; color: window.palette.text; font.pixelSize: 18; font.weight: Font.DemiBold }
                        RowLayout { Layout.fillWidth: true
                            Label { text: "Estimated"; color: window.palette.muted; font.pixelSize: 12 }
                            Label { text: appViewModel ? appViewModel.job_estimate : "—"; color: window.palette.text; font.pixelSize: 12 }
                            Item { Layout.fillWidth: true }
                            Label { visible: appViewModel && appViewModel.job_active; text: appViewModel ? appViewModel.job_time_remaining : ""; color: window.palette.accent; font.pixelSize: 12; font.weight: Font.DemiBold }
                        }
                        ProgressBar { Layout.fillWidth: true; from: 0; to: 100; value: appViewModel ? appViewModel.job_progress : 0; visible: appViewModel && appViewModel.job_file !== "No G-code loaded" }
                        Repeater { model: ["Machine is connected and Idle", "Virtual reference is trusted", "XYZ work zero is confirmed", "Job fits the virtual envelope"]
                            delegate: RowLayout { Layout.fillWidth: true; spacing: 8
                                property bool passed: index === 0 ? (appViewModel && appViewModel.grbl_state === "Idle") : index === 1 ? (appViewModel && appViewModel.reference_trusted) : index === 2 ? (appViewModel && appViewModel.work_zero_confirmed) : (appViewModel && appViewModel.job_file !== "No G-code loaded")
                                Rectangle { width: 17; height: 17; radius: 8.5; color: parent.passed ? Qt.rgba(window.palette.success.r, window.palette.success.g, window.palette.success.b, 0.18) : "transparent"; border.color: parent.passed ? window.palette.success : window.palette.subtle; border.width: 1; Label { anchors.centerIn: parent; text: parent.parent.passed ? "✓" : ""; color: window.palette.success; font.bold: true } }
                                Label { text: modelData; color: parent.passed ? window.palette.text : window.palette.muted; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            }
                        }
                        ModernCheckBox { Layout.fillWidth: true; palette: window.palette; text: "Material and tool are secure"; checked: appViewModel && appViewModel.guided_preflight_confirmed; onClicked: if (appViewModel) appViewModel.set_physical_preflight_confirmed(checked) }
                        Item { Layout.fillHeight: true }
                        PrimaryButton { Layout.fillWidth: true; text: "Start job"; enabled: appViewModel && appViewModel.can_start_job && appViewModel.guided_preflight_confirmed; opacity: enabled ? 1 : 0.55; onClicked: appViewModel.start_job() }
                        RowLayout { Layout.fillWidth: true
                            SecondaryButton { Layout.fillWidth: true; text: "Pause"; enabled: appViewModel && appViewModel.job_active; onClicked: appViewModel.pause_job() }
                            SecondaryButton { Layout.fillWidth: true; text: "Resume"; enabled: appViewModel && appViewModel.job_active; onClicked: appViewModel.resume_job() }
                            SecondaryButton { Layout.fillWidth: true; text: "Abort"; enabled: appViewModel && appViewModel.job_active; onClicked: appViewModel.abort_job() }
                        }
                        Divider {}
                        RowLayout { Layout.fillWidth: true
                            SecondaryButton { Layout.fillWidth: true; text: "Spindle on"; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.start_spindle(12000) }
                            SecondaryButton { Layout.fillWidth: true; text: "Spindle off"; enabled: appViewModel && appViewModel.connected; onClicked: appViewModel.stop_spindle() }
                        }
                    }
                }
            }
        }

        // Machine
        Item {
            id: machinePage
            property bool coordinatesExpanded: false
            RowLayout { anchors.fill: parent; spacing: 14
                Panel { Layout.preferredWidth: 210; Layout.minimumWidth: 210; Layout.maximumWidth: 210; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 16; spacing: 8
                        SectionTitle { text: "Machine" }
                        SecondaryButton { Layout.fillWidth: true; text: "Status"; onClicked: window.toastText = appViewModel.grbl_state + " · " + appViewModel.machine_position }
                        SecondaryButton { Layout.fillWidth: true; text: "Connection"; onClicked: connectionDialog.open() }
                        SecondaryButton { Layout.fillWidth: true; text: "Configure controller Wi-Fi"; enabled: appViewModel && appViewModel.connected; onClicked: wifiSetupDialog.open() }
                        SecondaryButton { Layout.fillWidth: true; text: "Machine profile"; onClicked: profileDialog.open() }
                        SecondaryButton { Layout.fillWidth: true; text: "Machine setup"; onClicked: machineSetupDialog.open() }
                        SecondaryButton { Layout.fillWidth: true; text: "Commissioning"; onClicked: commissioningDialog.open() }
                        ModernCheckBox { Layout.fillWidth: true; palette: window.palette; text: "Show expert details"; checked: appViewModel && appViewModel.expert_mode; onClicked: if (appViewModel) appViewModel.set_expert_mode(checked) }
                        SecondaryButton { Layout.fillWidth: true; text: "Coordinates"; onClicked: window.toastText = "Machine " + appViewModel.machine_position + " · Work " + appViewModel.work_position }
                        SecondaryButton { Layout.fillWidth: true; text: "Console"; onClicked: consoleDialog.open() }
                        SecondaryButton { Layout.fillWidth: true; text: "Guided setup"; onClicked: guidedSetupDialog.open() }
                        Item { Layout.fillHeight: true }
                        MutedLabel { text: "Reference and work zero are intentionally separate safety states." }
                    }
                }
                Panel { Layout.fillWidth: true; Layout.fillHeight: true
                    ToolpathCanvas { anchors.fill: parent; anchors.margins: 18; modeLabel: "MACHINE"; showEnvelope: true }
                }
                Panel { Layout.preferredWidth: 365; Layout.minimumWidth: 365; Layout.maximumWidth: 365; Layout.fillHeight: true
                    ScrollView { anchors.fill: parent; anchors.margins: 18; clip: true; contentWidth: availableWidth
                    ColumnLayout { width: parent.width; spacing: 12
                        SectionTitle { text: "Position the machine" }
                        MutedLabel { text: "Use small steps near the workpiece. Commands are ignored while GRBL is not Idle and are checked against the trusted envelope." }
                        RowLayout { Layout.fillWidth: true
                            Label { text: "Feed"; color: window.palette.muted; font.pixelSize: 12 }
                            Field { id: jogFeedField; Layout.preferredWidth: 78; text: "500"; validator: DoubleValidator { bottom: 1; top: 1500 } }
                            Label { text: "mm/min"; color: window.palette.subtle; font.pixelSize: 11 }
                            Item { Layout.fillWidth: true }
                        }
                        RowLayout { Layout.alignment: Qt.AlignHCenter; spacing: 12
                            Item {
                                id: xyJogPad
                                width: 214
                                height: 214

                                Rectangle { anchors.fill: parent; radius: 18; color: "#1D2025"; border.color: window.palette.divider; border.width: 1 }
                                Label { anchors.centerIn: parent; text: "XY"; color: window.palette.muted; font.pixelSize: 10; font.weight: Font.DemiBold }

                                // Outer ring: press and hold for live jogging; release stops at the nearest whole mm.
                                JogArrowButton { x: 76; y: 6; width: 62; height: 42; glyph: "▲\nY+"; enabled: appViewModel && (appViewModel.can_live_jog || appViewModel.live_jog_active); onPressed: appViewModel.start_live_jog("Y", 1); onReleased: appViewModel.stop_live_jog(); onCanceled: appViewModel.stop_live_jog() }
                                JogArrowButton { x: 7; y: 86; width: 58; height: 42; glyph: "◀\nX−"; enabled: appViewModel && (appViewModel.can_live_jog || appViewModel.live_jog_active); onPressed: appViewModel.start_live_jog("X", -1); onReleased: appViewModel.stop_live_jog(); onCanceled: appViewModel.stop_live_jog() }
                                JogArrowButton { x: 149; y: 86; width: 58; height: 42; glyph: "▶\nX+"; enabled: appViewModel && (appViewModel.can_live_jog || appViewModel.live_jog_active); onPressed: appViewModel.start_live_jog("X", 1); onReleased: appViewModel.stop_live_jog(); onCanceled: appViewModel.stop_live_jog() }
                                JogArrowButton { x: 76; y: 166; width: 62; height: 42; glyph: "▼\nY−"; enabled: appViewModel && (appViewModel.can_live_jog || appViewModel.live_jog_active); onPressed: appViewModel.start_live_jog("Y", -1); onReleased: appViewModel.stop_live_jog(); onCanceled: appViewModel.stop_live_jog() }

                                // Inner ring: one click moves the selected step.
                                JogArrowButton { x: 86; y: 58; width: 42; height: 24; glyph: "▲"; fine: true; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.jog("Y", 0.1) }
                                JogArrowButton { x: 72; y: 91; width: 24; height: 32; glyph: "◀"; fine: true; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.jog("X", -0.1) }
                                JogArrowButton { x: 118; y: 91; width: 24; height: 32; glyph: "▶"; fine: true; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.jog("X", 0.1) }
                                JogArrowButton { x: 86; y: 132; width: 42; height: 24; glyph: "▼"; fine: true; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.jog("Y", -0.1) }
                            }

                            ColumnLayout { Layout.alignment: Qt.AlignVCenter; spacing: 7
                                Label { text: "Z AXIS"; color: window.palette.subtle; font.pixelSize: 10; font.weight: Font.DemiBold; Layout.alignment: Qt.AlignHCenter }
                                JogArrowButton { Layout.preferredWidth: 76; Layout.preferredHeight: 47; glyph: "▲\nZ+"; enabled: appViewModel && (appViewModel.can_live_jog || appViewModel.live_jog_active); onPressed: appViewModel.start_live_jog("Z", 1); onReleased: appViewModel.stop_live_jog(); onCanceled: appViewModel.stop_live_jog() }
                                JogArrowButton { Layout.preferredWidth: 76; Layout.preferredHeight: 34; glyph: "Z+"; fine: true; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.jog("Z", 0.1) }
                                JogArrowButton { Layout.preferredWidth: 76; Layout.preferredHeight: 34; glyph: "Z−"; fine: true; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.jog("Z", -0.1) }
                                JogArrowButton { Layout.preferredWidth: 76; Layout.preferredHeight: 47; glyph: "▼\nZ−"; enabled: appViewModel && (appViewModel.can_live_jog || appViewModel.live_jog_active); onPressed: appViewModel.start_live_jog("Z", -1); onReleased: appViewModel.stop_live_jog(); onCanceled: appViewModel.stop_live_jog() }
                            }
                        }
                        Label { Layout.alignment: Qt.AlignHCenter; text: "Inner click: 0.1 mm  ·  Outer hold: live jog, nearest whole-mm stop"; color: window.palette.subtle; font.pixelSize: 10 }
                        SecondaryButton { Layout.alignment: Qt.AlignHCenter; width: 108; text: "Cancel jog"; enabled: appViewModel && appViewModel.connected; onClicked: appViewModel.cancel_jog() }
                        Divider {}
                        SecondaryButton { Layout.fillWidth: true; text: (machinePage.coordinatesExpanded ? "⌃  " : "⌄  ") + "Move to coordinates"; onClicked: machinePage.coordinatesExpanded = !machinePage.coordinatesExpanded }
                        GridLayout { visible: machinePage.coordinatesExpanded; Layout.fillWidth: true; columns: 2
                            Label { text: "X"; color: window.palette.muted }
                            Field { id: targetX; text: "0.00"; Layout.fillWidth: true; validator: DoubleValidator {} }
                            Label { text: "Y"; color: window.palette.muted }
                            Field { id: targetY; text: "0.00"; Layout.fillWidth: true; validator: DoubleValidator {} }
                            Label { text: "Z"; color: window.palette.muted }
                            Field { id: targetZ; text: "0.00"; Layout.fillWidth: true; validator: DoubleValidator {} }
                        }
                        SecondaryButton { visible: machinePage.coordinatesExpanded; Layout.fillWidth: true; text: "Move safely"; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.move_to(Number(targetX.text), Number(targetY.text), Number(targetZ.text), Number(jogFeedField.text)) }
                        Divider {}
                        PrimaryButton { Layout.fillWidth: true; text: "Establish reference"; enabled: appViewModel && appViewModel.connected && !appViewModel.job_active; onClicked: appViewModel.establish_reference() }
                        SecondaryButton { Layout.fillWidth: true; text: "Home machine"; enabled: appViewModel && appViewModel.can_home_machine; onClicked: appViewModel.home_machine() }
                        SecondaryButton { Layout.fillWidth: true; text: "Go to reference"; enabled: appViewModel && appViewModel.can_return_to_reference; onClicked: appViewModel.return_to_reference() }
                        SecondaryButton { Layout.fillWidth: true; text: "Retract to safe Z"; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.retract_safe_z() }
                        GridLayout { Layout.fillWidth: true; columns: 4; columnSpacing: 6
                            SecondaryButton { Layout.fillWidth: true; text: "Zero X"; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.set_work_zero("X") }
                            SecondaryButton { Layout.fillWidth: true; text: "Zero Y"; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.set_work_zero("Y") }
                            SecondaryButton { Layout.fillWidth: true; text: "Zero Z"; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.set_work_zero("Z") }
                            PrimaryButton { Layout.fillWidth: true; text: "Zero XYZ"; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.set_work_zero("XYZ") }
                        }
                        SecondaryButton { Layout.fillWidth: true; text: "Return to work zero"; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.return_to_work_zero() }
                    }
                    }
                }
            }
        }

        // Guided setup is retained as a modal workflow, opened from Machine.
        Dialog {
            id: guidedSetupDialog
            modal: true
            title: "Guided setup"
            width: 1080
            height: Math.min(740, window.usableContentHeight - 24)
            x: Math.round((window.width - width) / 2)
            y: Math.round((window.usableContentHeight - height) / 2)
            standardButtons: Dialog.NoButton
            background: Rectangle { color: window.palette.surface; radius: 14; border.color: window.palette.divider; border.width: 1 }
            RowLayout { anchors.fill: parent; spacing: 14
                Panel { Layout.preferredWidth: 265; Layout.minimumWidth: 265; Layout.maximumWidth: 265; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 18; spacing: 6
                        SectionTitle { text: "Guided setup" }
                        MutedLabel { text: "A clear, safety-gated path from connection to engraving."; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Divider {}
                        Repeater { model: appViewModel ? appViewModel.guided_step_names : []
                            delegate: RowLayout { Layout.fillWidth: true; Layout.preferredHeight: 32; spacing: 9
                                Rectangle {
                                    width: 19; height: 19; radius: 9.5
                                    color: index === appViewModel.guided_step ? window.palette.accent : index < appViewModel.guided_step ? window.palette.success : window.palette.raised
                                    Label { anchors.centerIn: parent; text: index < appViewModel.guided_step ? "✓" : index + 1; color: index <= appViewModel.guided_step ? "white" : window.palette.muted; font.pixelSize: 10; font.bold: true }
                                }
                                Label { text: modelData; color: index === appViewModel.guided_step ? window.palette.text : window.palette.muted; font.pixelSize: 12; Layout.fillWidth: true; elide: Text.ElideRight }
                            }
                        }
                        Item { Layout.fillHeight: true }
                        SecondaryButton { Layout.fillWidth: true; text: "Start over"; onClicked: appViewModel.guided_reset() }
                    }
                }
                Panel { Layout.fillWidth: true; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 48; spacing: 18
                        Pill { label: "Step " + (appViewModel ? appViewModel.guided_step + 1 : 1) + " of " + (appViewModel ? appViewModel.guided_step_count : 9); tone: window.palette.accent }
                        Label { text: appViewModel ? appViewModel.guided_step_title : "Guided setup"; color: window.palette.text; font.pixelSize: 30; font.weight: Font.Bold }
                        Label { text: appViewModel ? appViewModel.guided_step_description : ""; color: window.palette.muted; font.pixelSize: 16; wrapMode: Text.Wrap; Layout.maximumWidth: 760; Layout.fillWidth: true }
                        Divider {}

                        ColumnLayout { visible: appViewModel && appViewModel.guided_step === 0; Layout.fillWidth: true; spacing: 12
                            Repeater { model: ["Keep physical power removal or an emergency stop within reach.", "Do not drive axes into mechanical stops.", "Confirm the spindle is off before reference and setup moves.", "No homing switches or probe are assumed in this workflow."]
                                delegate: RowLayout { Layout.fillWidth: true; spacing: 10
                                    Rectangle { width: 19; height: 19; radius: 4; color: Qt.rgba(window.palette.accent.r, window.palette.accent.g, window.palette.accent.b, 0.18); Label { anchors.centerIn: parent; text: "✓"; color: window.palette.accent; font.bold: true } }
                                    Label { text: modelData; color: window.palette.text; font.pixelSize: 14; Layout.fillWidth: true; wrapMode: Text.Wrap }
                                }
                            }
                            SecondaryButton { Layout.fillWidth: true; text: "Load existing job…"; onClicked: gcodeFileDialog.open() }
                        }
                        ColumnLayout { visible: appViewModel && appViewModel.guided_step === 1; Layout.fillWidth: true; spacing: 12
                            PrimaryButton { text: "Open connection"; onClicked: connectionDialog.open() }
                        }
                        ColumnLayout { visible: appViewModel && appViewModel.guided_step === 2; Layout.fillWidth: true; spacing: 12
                            Label { text: appViewModel ? appViewModel.profile_summary : ""; color: window.palette.text; font.pixelSize: 15 }
                            SecondaryButton { text: "Edit machine profile"; onClicked: profileDialog.open() }
                        }
                        ColumnLayout { visible: appViewModel && appViewModel.guided_step === 3; Layout.fillWidth: true; spacing: 12
                            Label { text: "Current machine: " + (appViewModel ? appViewModel.machine_position : "—"); color: window.palette.text; font.family: "Cascadia Mono" }
                                SecondaryButton { text: "Open machine controls"; onClicked: { guidedSetupDialog.close(); window.workspace = 2 } }
                        }
                        ColumnLayout { visible: appViewModel && appViewModel.guided_step === 4; Layout.fillWidth: true; spacing: 12
                            Label { text: "Current work position: " + (appViewModel ? appViewModel.work_position : "—"); color: window.palette.text; font.family: "Cascadia Mono" }
                                SecondaryButton { text: "Open machine controls"; onClicked: { guidedSetupDialog.close(); window.workspace = 2 } }
                        }
                        ColumnLayout { visible: appViewModel && appViewModel.guided_step === 5; Layout.fillWidth: true; spacing: 12
                            Label { text: appViewModel ? appViewModel.job_file : "No job loaded"; color: window.palette.text; font.pixelSize: 15 }
                            RowLayout { Layout.fillWidth: true; spacing: 10
                                SecondaryButton { text: "Open Prepare"; onClicked: { guidedSetupDialog.close(); window.workspace = 0 } }
                                SecondaryButton { text: "Open Preview & Run"; onClicked: { guidedSetupDialog.close(); window.workspace = 1 } }
                            }
                        }
                        ColumnLayout { visible: appViewModel && appViewModel.guided_step === 6; Layout.fillWidth: true; spacing: 12
                            Label { text: appViewModel ? appViewModel.job_summary : ""; color: window.palette.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            SecondaryButton { text: "Review job"; onClicked: { guidedSetupDialog.close(); window.workspace = 1 } }
                        }
                        ColumnLayout { visible: appViewModel && appViewModel.guided_step === 7; Layout.fillWidth: true; spacing: 12
                            Label { text: "Confirm that the material is secured, the tool is tightened, the spindle behavior is understood, safe Z is clear, and emergency power removal is available."; color: window.palette.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            ModernCheckBox { id: guidedPreflightCheck; palette: window.palette; text: "I have completed the physical preflight"; checked: appViewModel ? appViewModel.guided_preflight_confirmed : false; onClicked: appViewModel.confirm_guided_preflight() }
                        }
                        ColumnLayout { visible: appViewModel && appViewModel.guided_step === 8; Layout.fillWidth: true; spacing: 12
                            Label { text: "The job will use acknowledged, capacity-limited GRBL streaming. Keep watching the machine throughout the run."; color: window.palette.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            PrimaryButton { text: "Start guarded job"; enabled: appViewModel && appViewModel.can_start_job; onClicked: appViewModel.guided_start_job() }
                        }
                        Label { text: appViewModel ? appViewModel.guided_step_reason : ""; color: appViewModel && appViewModel.guided_step_ready ? window.palette.success : window.palette.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Item { Layout.fillHeight: true }
                        RowLayout { Layout.fillWidth: true
                            SecondaryButton { text: "Back"; enabled: appViewModel && appViewModel.guided_step > 0; onClicked: appViewModel.guided_previous() }
                            Item { Layout.fillWidth: true }
                            PrimaryButton { text: appViewModel && appViewModel.guided_step === appViewModel.guided_step_count - 1 ? "Done" : "Next"; enabled: appViewModel && appViewModel.guided_step_ready; onClicked: appViewModel && appViewModel.guided_step === appViewModel.guided_step_count - 1 ? guidedSetupDialog.close() : appViewModel.guided_next() }
                        }
                    }
                }
            }
        }

    }

    component IsometricCanvas: Item {
        property string modeLabel: "3D PREVIEW"

        Rectangle { anchors.fill: parent; radius: 9; color: "#1D2025"; border.color: window.palette.divider; border.width: 1 }
        Canvas {
            id: isoCanvas
            anchors.fill: parent
            anchors.margins: 18
            onPaint: {
                const ctx = getContext("2d")
                ctx.reset()
                ctx.fillStyle = "#1D2025"
                ctx.fillRect(0, 0, width, height)

                const faces = appViewModel ? appViewModel.step_isometric_faces : []
                const paths = appViewModel ? appViewModel.step_isometric_paths : []
                const stockWidth = appViewModel ? Number(appViewModel.preview_stock_width || appViewModel.step_suggested_stock_width || 0) : 0
                const stockHeight = appViewModel ? Number(appViewModel.preview_stock_height || appViewModel.step_suggested_stock_height || 0) : 0
                const stockThickness = appViewModel ? Number(appViewModel.step_isometric_stock_thickness || 0) : 0

                function project(point) {
                    return [(point[0] - point[1]) * 0.8660254, (point[0] + point[1]) * 0.5 - point[2] * 0.9]
                }
                const stockPoints = stockWidth > 0 && stockHeight > 0 && stockThickness > 0 ? [
                    [0, 0, 0], [stockWidth, 0, 0], [stockWidth, stockHeight, 0], [0, stockHeight, 0],
                    [0, 0, -stockThickness], [stockWidth, 0, -stockThickness], [stockWidth, stockHeight, -stockThickness], [0, stockHeight, -stockThickness]
                ] : []
                let projected = []
                for (const face of faces) for (const loop of face.loops) for (const point of loop) projected.push(project(point))
                for (const path of paths) for (const point of path.points) projected.push(project(point))
                for (const point of stockPoints) projected.push(project(point))
                if (projected.length === 0) {
                    ctx.fillStyle = "#737B87"
                    ctx.font = "14px sans-serif"
                    ctx.textAlign = "center"
                    ctx.fillText("Import a STEP model to see the 3D machining proposal", width / 2, height / 2)
                    return
                }
                let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
                for (const point of projected) {
                    minX = Math.min(minX, point[0]); minY = Math.min(minY, point[1])
                    maxX = Math.max(maxX, point[0]); maxY = Math.max(maxY, point[1])
                }
                const margin = 54
                const scale = Math.min((width - margin * 2) / Math.max(0.001, maxX - minX), (height - margin * 2) / Math.max(0.001, maxY - minY))
                const offsetX = (width - (maxX - minX) * scale) / 2 - minX * scale
                const offsetY = (height - (maxY - minY) * scale) / 2 - minY * scale
                function screen(point) {
                    const result = project(point)
                    return [offsetX + result[0] * scale, offsetY + result[1] * scale]
                }

                if (stockPoints.length) {
                    const edges = [[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]]
                    ctx.setLineDash([6, 5])
                    ctx.strokeStyle = "#586575"
                    ctx.lineWidth = 1.4
                    for (const edge of edges) {
                        const start = screen(stockPoints[edge[0]]), end = screen(stockPoints[edge[1]])
                        ctx.beginPath(); ctx.moveTo(start[0], start[1]); ctx.lineTo(end[0], end[1]); ctx.stroke()
                    }
                    ctx.setLineDash([])
                }

                const orderedFaces = Array.prototype.slice.call(faces)
                orderedFaces.sort(function(a, b) {
                    function average(face) {
                        let total = 0, count = 0
                        for (const loop of face.loops) for (const point of loop) { total += project(point)[1]; count++ }
                        return count ? total / count : 0
                    }
                    return average(a) - average(b)
                })
                const fills = { surface: "#315A7F", ramp: "#2E6F9E", side: "#263A4D", feature: "#5B4A36", bottom: "#202B36" }
                for (const face of orderedFaces) {
                    ctx.beginPath()
                    for (const loop of face.loops) {
                        if (!loop.length) continue
                        const first = screen(loop[0]); ctx.moveTo(first[0], first[1])
                        for (let index = 1; index < loop.length; index++) {
                            const point = screen(loop[index]); ctx.lineTo(point[0], point[1])
                        }
                        ctx.closePath()
                    }
                    ctx.fillStyle = fills[face.kind] || fills.surface
                    ctx.globalAlpha = face.kind === "bottom" ? 0.55 : 0.90
                    ctx.fill()
                    ctx.globalAlpha = 1
                    ctx.strokeStyle = face.kind === "feature" ? "#B08A56" : "#7E93A9"
                    ctx.lineWidth = 1.1
                    ctx.stroke()
                }

                ctx.lineCap = "round"
                ctx.lineJoin = "round"
                for (const path of paths) {
                    if (!path.points.length) continue
                    ctx.strokeStyle = path.kind === "profile" ? "#40C4D9" : path.kind === "surface" ? "#168BFF" : "#63AFFF"
                    ctx.lineWidth = path.kind === "profile" ? 3.2 : 2.3
                    const first = screen(path.points[0]); ctx.beginPath(); ctx.moveTo(first[0], first[1])
                    for (let index = 1; index < path.points.length; index++) {
                        const point = screen(path.points[index]); ctx.lineTo(point[0], point[1])
                    }
                    ctx.stroke()
                }

                const zero = screen([0, 0, 0])
                ctx.fillStyle = "#40C4D9"
                ctx.beginPath(); ctx.arc(zero[0], zero[1], 5, 0, Math.PI * 2); ctx.fill()
            }
        }
        Connections { target: appViewModel; function onPreview_changed() { isoCanvas.requestPaint() } function onState_changed() { if (!appViewModel || appViewModel.preview_strokes.length === 0) isoCanvas.requestPaint() } }
        Row { anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 14; spacing: 8
            Pill { label: parent.parent.modeLabel; tone: window.palette.accent }
            Pill { visible: appViewModel && appViewModel.step_isometric_paths.length > 0; label: "Validated proposal"; tone: window.palette.success }
        }
        Row { anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 14; spacing: 14
            Label { text: "● Work zero"; color: window.palette.success; font.pixelSize: 11 }
            Label { text: "— Model"; color: "#7E93A9"; font.pixelSize: 11 }
            Label { text: "— Toolpath"; color: window.palette.accent; font.pixelSize: 11 }
            Label { text: "— Final profile"; color: window.palette.success; font.pixelSize: 11 }
        }
    }

    component ToolpathCanvas: Item {
        property string modeLabel: "PREVIEW"
        property bool showJob: false
        property bool showEnvelope: false

        Rectangle { anchors.fill: parent; radius: 9; color: "#1D2025"; border.color: window.palette.divider; border.width: 1 }
        Canvas {
            id: canvas
            anchors.fill: parent
            anchors.margins: 20
            onPaint: {
                const ctx = getContext("2d")
                ctx.reset()
                ctx.fillStyle = "#1D2025"
                ctx.fillRect(0, 0, width, height)
                const step = Math.max(24, Math.min(width, height) / 14)
                ctx.lineWidth = 1
                ctx.strokeStyle = "#30353E"
                for (let x = 0; x <= width; x += step) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke() }
                for (let y = 0; y <= height; y += step) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke() }
                const inset = Math.min(width, height) * 0.13
                let workZeroX = inset
                let workZeroY = height - inset
                const stockWidth = appViewModel ? Number(appViewModel.preview_stock_width || 0) : 0
                const stockHeight = appViewModel ? Number(appViewModel.preview_stock_height || 0) : 0
                const hasStock = stockWidth > 0 && stockHeight > 0
                if (!hasStock) {
                    ctx.strokeStyle = "#4B5867"
                    ctx.lineWidth = 2
                    ctx.strokeRect(inset, inset, width - inset * 2, height - inset * 2)
                }
                if ((showJob || modeLabel === "PREPARE") && (!appViewModel || appViewModel.preview_strokes.length === 0)) {
                    const l = inset + (width - inset * 2) * 0.20
                    const t = inset + (height - inset * 2) * 0.25
                    const w = (width - inset * 2) * 0.56
                    const h = (height - inset * 2) * 0.44
                    ctx.strokeStyle = "#168BFF"
                    ctx.lineWidth = 2.5
                    ctx.strokeRect(l, t, w, h)
                    ctx.beginPath()
                    ctx.moveTo(l + w * .18, t + h * .64)
                    ctx.lineTo(l + w * .82, t + h * .64)
                    ctx.moveTo(l + w * .26, t + h * .38)
                    ctx.lineTo(l + w * .74, t + h * .38)
                    ctx.stroke()
                    ctx.setLineDash([6, 5])
                    ctx.strokeStyle = "#657282"
                    ctx.beginPath(); ctx.moveTo(inset, height - inset); ctx.lineTo(l, t + h); ctx.stroke(); ctx.setLineDash([])
                }
                if (appViewModel && appViewModel.preview_strokes.length > 0) {
                    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
                    const modelStrokes = appViewModel.preview_model_strokes || []
                    const allStrokes = modelStrokes.concat(appViewModel.preview_strokes)
                    for (const stroke of allStrokes) for (const point of stroke) {
                        minX = Math.min(minX, point[0]); minY = Math.min(minY, point[1]); maxX = Math.max(maxX, point[0]); maxY = Math.max(maxY, point[1])
                    }
                    if (hasStock) {
                        minX = Math.min(minX, 0); minY = Math.min(minY, 0)
                        maxX = Math.max(maxX, stockWidth); maxY = Math.max(maxY, stockHeight)
                    }
                    const spanX = Math.max(0.001, maxX - minX), spanY = Math.max(0.001, maxY - minY)
                    const scale = Math.min((width - 2 * inset) / spanX, (height - 2 * inset) / spanY)
                    const offsetX = (width - spanX * scale) / 2 - minX * scale
                    const offsetY = height - inset + minY * scale
                    workZeroX = offsetX
                    workZeroY = offsetY
                    if (hasStock) {
                        ctx.setLineDash([6, 4]); ctx.strokeStyle = "#657282"; ctx.lineWidth = 1.8
                        ctx.strokeRect(offsetX, offsetY - stockHeight * scale, stockWidth * scale, stockHeight * scale)
                        ctx.setLineDash([])
                    }
                    ctx.setLineDash([7, 5]); ctx.strokeStyle = "#F2B84B"; ctx.lineWidth = 1.8
                    for (const stroke of modelStrokes) {
                        if (!stroke.length) continue
                        ctx.beginPath(); ctx.moveTo(offsetX + stroke[0][0] * scale, offsetY - stroke[0][1] * scale)
                        for (let index = 1; index < stroke.length; index++) ctx.lineTo(offsetX + stroke[index][0] * scale, offsetY - stroke[index][1] * scale)
                        ctx.stroke()
                    }
                    ctx.setLineDash([])
                    ctx.strokeStyle = "#168BFF"; ctx.lineWidth = 2.2; ctx.lineCap = "round"; ctx.lineJoin = "round"
                    for (const stroke of appViewModel.preview_strokes) {
                        if (!stroke.length) continue
                        ctx.beginPath(); ctx.moveTo(offsetX + stroke[0][0] * scale, offsetY - stroke[0][1] * scale)
                        for (let index = 1; index < stroke.length; index++) ctx.lineTo(offsetX + stroke[index][0] * scale, offsetY - stroke[index][1] * scale)
                        ctx.stroke()
                    }
                }
                ctx.fillStyle = "#40C4D9"
                ctx.beginPath(); ctx.arc(workZeroX, workZeroY, 6, 0, Math.PI * 2); ctx.fill()
            }
        }
        Connections { target: appViewModel; function onPreview_changed() { canvas.requestPaint() } function onState_changed() { if (!appViewModel || appViewModel.preview_strokes.length === 0) canvas.requestPaint() } }
        Row { anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 14; spacing: 8
            Pill { label: parent.parent.modeLabel; tone: window.palette.accent }
            Pill { visible: parent.parent.showEnvelope; label: "Virtual envelope"; tone: window.palette.warning }
        }
        Column { anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 14; spacing: 6
            Repeater { model: ["Fit", "+", "−", "Top"]
                delegate: SecondaryButton { width: 52; padding: 5; text: modelData; onClicked: appViewModel.show_preview_notice(text + " view") }
            }
        }
        Row { anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 14; spacing: 15
            Label { text: "● Work zero"; color: window.palette.success; font.pixelSize: 11 }
            Label { visible: !appViewModel || appViewModel.preview_stock_width <= 0; text: "— Travel envelope"; color: window.palette.muted; font.pixelSize: 11 }
            Label { visible: appViewModel && appViewModel.preview_stock_width > 0; text: "— Physical stock"; color: window.palette.muted; font.pixelSize: 11 }
            Label { text: "— Cutting path"; color: window.palette.accent; font.pixelSize: 11 }
        }
    }

    Rectangle {
        visible: window.toastText.length > 0
        z: 10
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 76
        width: Math.min(620, toastLabel.implicitWidth + 42)
        height: Math.max(46, toastLabel.implicitHeight + 24)
        radius: 9
        color: "#303640"
        border.color: window.palette.divider
        border.width: 1
        Label { id: toastLabel; anchors.centerIn: parent; width: parent.width - 32; text: window.toastText; color: window.palette.text; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 12 }
    }
}
