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
        background: Qt.color("#0F0F10"), surface: Qt.color("#1C1C1E"),
        raised: Qt.color("#2C2C2E"), elevated: Qt.color("#3A3A3C"),
        input: Qt.color("#151517"), hover: Qt.color("#3A3A3C"),
        accent: Qt.color("#0A84FF"), accentHover: Qt.color("#409CFF"),
        text: Qt.color("#F5F5F7"), muted: Qt.color("#AEAEB2"),
        subtle: Qt.color("#7C7C80"), divider: Qt.color("#3A3A3C"),
        warning: Qt.color("#FF9F0A"), danger: Qt.color("#FF453A"),
        success: Qt.color("#30D158")
    })

    // The safety/workflow model remains canonical internally, while the shell
    // exposes each applicable operator step as compact top navigation.
    property int guidedIndex: appViewModel ? appViewModel.guided_step : 1
    property bool configureOpen: false
    // Stack order is Configure, Prepare, Job, Machine. Direct
    // guidedIndex overrides remain useful to headless render fixtures.
    readonly property bool inMachineWorkspace: guidedIndex >= 1 && guidedIndex <= 3 && !configureOpen
    readonly property int machineSetupStep: !appViewModel || !appViewModel.connected ? 1 : (!appViewModel.reference_trusted ? 2 : 3)
    readonly property int guidedContentIndex: guidedIndex === 0 ? 0 : (guidedIndex === 4 ? 1 : (guidedIndex >= 5 ? 2 : 3))
    readonly property int effectiveContentIndex: configureOpen ? 0 : guidedContentIndex
    readonly property int setup_section_index: setupPage.sectionIndex
    property string toastText: ""
    property string selectedTransport: "USB serial"
    property real jogStep: 0.1
    property bool zProbeWasConnected: false
    property string zProbeLastBackendSession: ""
    property string zProbeDismissedTransactionKey: ""
    property string zProbeDismissedBackendSession: ""
    property string zProbeCurrentTransactionKey: ""
    property string zProbeTransactionSession: ""
    property string zProbeObservedState: ""
    property string zProbeLastFailureKey: ""
    property int zProbeLocalTransactionCounter: 0
    readonly property real usableContentHeight: height - header.height - footer.height

    // A pointer release can be lost when the window loses focus. Treat focus
    // loss as a release so a held jog can never continue in the background.
    onActiveChanged: {
        if (!active && appViewModel && appViewModel.live_jog_active)
            appViewModel.stop_live_jog()
    }
    Component.onDestruction: if (appViewModel) appViewModel.stop_live_jog()
    Connections {
        target: appViewModel
        function onState_changed() {
            if (appViewModel && appViewModel.travel_calibration_active)
                window.configureOpen = false
            window.syncZProbeResultDialog()
        }
    }

    function syncZProbeResultDialog() {
        if (!appViewModel)
            return

        const connected = Boolean(appViewModel.connected)
        const backendSession = String(appViewModel.z_probe_backend_session_id || "")
        const backendSessionChanged = zProbeLastBackendSession.length > 0
            && backendSession !== zProbeLastBackendSession
        const reconnected = connected && (!zProbeWasConnected || backendSessionChanged)
        if (reconnected || zProbeTransactionSession !== backendSession) {
            zProbeDismissedTransactionKey = ""
            zProbeDismissedBackendSession = ""
            zProbeCurrentTransactionKey = ""
            zProbeTransactionSession = backendSession
            zProbeLocalTransactionCounter = 0
            zProbeObservedState = ""
        }
        zProbeWasConnected = connected
        zProbeLastBackendSession = backendSession

        let completion = {}
        try {
            completion = JSON.parse(appViewModel.z_probe_completion_json || "{}")
        } catch (error) {
            completion = { state: "idle", message: "Z-probe result is unavailable" }
        }
        const state = String(completion.state || "idle")
        const transactionId = String(completion.transaction_id || "")
        if (transactionId.length > 0) {
            const backendTransactionKey = "backend:" + transactionId
            if (state === "waiting-removal"
                    && zProbeDismissedBackendSession === backendSession
                    && zProbeDismissedTransactionKey === zProbeCurrentTransactionKey
                    && zProbeCurrentTransactionKey.indexOf("local:") === 0)
                zProbeDismissedTransactionKey = backendTransactionKey
            zProbeCurrentTransactionKey = backendTransactionKey
        } else if (state === "probing" && zProbeObservedState !== "probing") {
            zProbeLocalTransactionCounter += 1
            zProbeCurrentTransactionKey = "local:" + backendSession + ":" + zProbeLocalTransactionCounter
        } else if (state === "idle") {
            zProbeCurrentTransactionKey = ""
        } else if (zProbeCurrentTransactionKey.length === 0) {
            zProbeCurrentTransactionKey = "local:" + backendSession + ":" + zProbeLocalTransactionCounter
        }
        zProbeObservedState = state

        if (state === "failed") {
            const failureMessage = String(completion.message || "Z-probe descent failed; review the backend status.")
            const failureKey = zProbeCurrentTransactionKey + ":" + failureMessage
            if (failureKey !== zProbeLastFailureKey) {
                zProbeLastFailureKey = failureKey
                toastText = failureMessage
                toastTimer.restart()
            }
        }

        if (zProbeResultDialog.visible) {
            zProbeResultDialog.completionSnapshot = completion
            zProbeResultDialog.transactionKey = zProbeCurrentTransactionKey
            zProbeResultDialog.backendSessionId = backendSession
        }
        const continuationStateOnReconnect = reconnected
            && (state === "lowering" || state === "complete" || state === "failed")
        if ((state !== "waiting-removal" && !continuationStateOnReconnect) || zProbeResultDialog.visible)
            return
        if (zProbeDismissedTransactionKey === zProbeCurrentTransactionKey
                && zProbeDismissedBackendSession === backendSession)
            return

        zProbeResultDialog.completionSnapshot = completion
        zProbeResultDialog.transactionKey = zProbeCurrentTransactionKey
        zProbeResultDialog.backendSessionId = backendSession
        zProbeResultDialog.open()
    }

    Component.onCompleted: syncZProbeResultDialog()

    function routeIssueAction(action) {
        if (action === "Connect" || action === "Reconnect") { selectGuidedStep(1); return }
        if (action === "Reload job") { selectGuidedStep(5); return }
        if (action === "Open console") { if (appViewModel && appViewModel.expert_mode) consoleDialog.open(); else selectGuidedStep(0); return }
        if (action === "Open Configure" || action === "Open Setup") { selectGuidedStep(0); return }
        if (action === "Open Run") { selectGuidedStep(6); return }
        selectGuidedStep(2)
    }

    function showSimulator() {
        if (!(appViewModel && appViewModel.simulation_active)) return
        simulationWindow.visible = true
        simulationWindow.raise()
        simulationWindow.requestActivate()
    }

    function selectSetupSection(index) { setupPage.sectionIndex = Math.max(0, Math.min(4, Number(index))) }
    function openConfigure() {
        configureOpen = true
    }
    function selectGuidedStep(index) {
        if (!appViewModel) return
        if (Number(index) === 0) {
            openConfigure()
        } else {
            configureOpen = false
        }
        appViewModel.select_guided_step(Number(index))
    }
    function guidedState(index) {
        const step = appViewModel && appViewModel.workflow_steps[index]
        if (!step) return "upcoming"
        if (Number(index) === Number(guidedIndex)) return step.state === "complete" ? "complete" : "current"
        if (step.state === "complete") return "complete"
        if (!step.selectable || step.state === "blocked") return "blocked"
        return "upcoming"
    }
    function axisDeclaration(axis) {
        try {
            const declarations = JSON.parse(appViewModel ? appViewModel.homing_limit_declarations_json : "{}")
            const item = declarations[axis] || {}
            return (item.enabled ? "switch " + String(item.end || "min") : "no switch")
                + " · pin " + String(item.pin || "—")
                + " · " + (item.active_low ? "active-low" : "active-high")
                + " · " + (item.hard_limit ? "hard-limit" : "soft-limit")
                + " · debounce " + Number(item.debounce_ms || 0).toFixed(1) + " ms"
                + " · max " + (item.max_override === null || item.max_override === undefined ? "default" : String(item.max_override))
        } catch (error) {
            return "declaration unavailable"
        }
    }
    function allHomingSwitchesEnabled() {
        try {
            const declarations = JSON.parse(appViewModel ? appViewModel.homing_limit_declarations_json : "{}")
            return ["X", "Y", "Z"].every(axis => Boolean(declarations[axis] && declarations[axis].enabled))
        } catch (error) {
            return false
        }
    }
    function workflowMethod(key) {
        const methods = appViewModel ? appViewModel.work_zero_methods : []
        return methods.find(item => item.key === key) || { label: key, state: "blocked", available: false, reason: "Unavailable", action: "Open Setup" }
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
        function onAuto_connection_failed(message) { connectionDialog.open() }
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
            Label { text: "The machine has not been homed."; color: window.palette.text; font.pixelSize: 16; font.weight: Font.DemiBold }
            MutedLabel { text: "Cautious setup jogs are allowed only after you confirm that you are watching the machine and will stop before a physical limit. Software envelope checks remain inactive until a successful home cycle." }
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
        objectName: "connectionDialog"
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
            Label { visible: appViewModel && appViewModel.auto_connection_state === "failed"; text: appViewModel && appViewModel.auto_connection_attempts.length > 0 ? "Automatic attempts: " + appViewModel.auto_connection_attempts.join(" · ") : "Automatic connection failed — choose an endpoint."; color: window.palette.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { text: "Transport"; color: window.palette.subtle; font.pixelSize: 11 }
            ComboBox { id: transportCombo; Layout.fillWidth: true; model: ["USB serial", "Wi-Fi TCP", "Virtual Machine (Digital Twin)"]; currentIndex: appViewModel && appViewModel.preferred_transport === "Wi-Fi TCP" ? 1 : 0; onActivated: window.selectedTransport = currentText }

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

            ColumnLayout {
                visible: transportCombo.currentText === "Virtual Machine (Digital Twin)"
                Layout.fillWidth: true
                spacing: 7
                Label { text: "Digital twin"; color: window.palette.subtle; font.pixelSize: 11 }
                Label { text: "Runs an isolated TTC 3018 controller on loopback. No serial port or physical/network controller will be accessed."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                RowLayout { Layout.fillWidth: true
                    Label { text: "Speed"; color: window.palette.muted }
                    ComboBox { id: simulationSpeed; Layout.fillWidth: true; model: ["Realtime", "2×", "5×", "10×", "Uncapped"]; currentIndex: appViewModel && appViewModel.simulation_speed ? model.indexOf(appViewModel.simulation_speed) : 0 }
                    Label { text: "Workpiece"; color: window.palette.muted }
                    ComboBox { id: simulationWorkpiece; Layout.fillWidth: true; model: ["Pocket + retained island", "Collision-only STEP"]; currentIndex: appViewModel && appViewModel.simulation_workpiece === "Collision-only STEP" ? 1 : 0 }
                }
            }

            Item { Layout.fillHeight: true }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { visible: appViewModel && appViewModel.connected; text: "Disconnect"; onClicked: { appViewModel.disconnect(); connectionDialog.close() } }
                SecondaryButton { text: "Cancel"; onClicked: connectionDialog.close() }
                PrimaryButton {
                    text: transportCombo.currentText === "Virtual Machine (Digital Twin)" ? "Start Digital Twin" : "Connect"
                    enabled: appViewModel && (transportCombo.currentText === "USB serial" ? portCombo.currentText.length > 0 : transportCombo.currentText === "Virtual Machine (Digital Twin)" ? true : wifiHostField.text.trim().length > 0)
                    onClicked: {
                        if (transportCombo.currentText === "USB serial") appViewModel.connect_to_usb(portCombo.currentText)
                        else if (transportCombo.currentText === "Wi-Fi TCP") appViewModel.connect_to_wifi(wifiHostField.text, Number(wifiPortField.text))
                        else { appViewModel.configure_simulation(simulationSpeed.currentText, simulationWorkpiece.currentText); appViewModel.connect_to_simulation() }
                        connectionDialog.close()
                    }
                }
            }
        }
    }

    Window {
        id: simulationWindow
        visible: appViewModel && appViewModel.simulation_active
        title: "Pine — Digital Twin — NO PHYSICAL MACHINE"
        width: 980
        height: 680
        minimumWidth: 720
        minimumHeight: 520
        color: window.palette.background
        flags: Qt.Window
        onClosing: function(closeEvent) {
            if (appViewModel && appViewModel.job_active) {
                closeEvent.accepted = false
                appViewModel.show_preview_notice("Stop or abort the simulated job before closing the digital-twin window.")
            }
        }
        ColumnLayout { anchors.fill: parent; anchors.margins: 16; spacing: 10
            RowLayout { Layout.fillWidth: true
                Label { text: appViewModel ? appViewModel.simulation_banner : "DIGITAL TWIN — NO PHYSICAL MACHINE"; color: window.palette.accent; font.weight: Font.Bold; font.pixelSize: 15 }
                Item { Layout.fillWidth: true }
                Label { text: appViewModel && appViewModel.simulation_supervisor_healthy ? "Supervisor: healthy" : "Supervisor: unavailable"; color: appViewModel && appViewModel.simulation_supervisor_healthy ? window.palette.success : window.palette.danger }
            }
            RowLayout { Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
                Rectangle { Layout.fillWidth: true; Layout.fillHeight: true; color: "#12161B"; radius: 10; border.color: window.palette.divider
                    Canvas { id: simulationCanvas; anchors.fill: parent; anchors.margins: 12
                        onPaint: {
                            const ctx = getContext("2d")
                            ctx.reset(); ctx.fillStyle = "#12161B"; ctx.fillRect(0, 0, width, height)
                            ctx.strokeStyle = "#536274"; ctx.lineWidth = 3; ctx.strokeRect(32, height - 42, width - 64, 18)
                            ctx.strokeStyle = "#65788B"; ctx.lineWidth = 5; ctx.beginPath(); ctx.moveTo(50, height - 42); ctx.lineTo(50, 52); ctx.moveTo(width - 50, height - 42); ctx.lineTo(width - 50, 52); ctx.moveTo(50, 52); ctx.lineTo(width - 50, 52); ctx.stroke()
                            const text = appViewModel ? appViewModel.machine_position : "X0  Y0  Z0"
                            const xMatch = text.match(/X([^ ]+)/); const yMatch = text.match(/Y([^ ]+)/); const zMatch = text.match(/Z([^ ]+)/)
                            const px = xMatch ? Number(xMatch[1]) : 0; const py = yMatch ? Number(yMatch[1]) : 0; const pz = zMatch ? Number(zMatch[1]) : 0
                            const tx = 50 + Math.max(0, Math.min(290, px)) / 290 * (width - 100)
                            const ty = height - 42 - Math.max(0, Math.min(170, py)) / 170 * (height - 110)
                            ctx.strokeStyle = "#40C4D9"; ctx.lineWidth = 4; ctx.beginPath(); ctx.moveTo(tx, 52); ctx.lineTo(tx, ty); ctx.stroke()
                            ctx.fillStyle = "#ED5B5B"; ctx.beginPath(); ctx.arc(tx, ty - Math.max(0, Math.min(40, pz)) * 1.4, 7, 0, Math.PI * 2); ctx.fill()
                            if (appViewModel && appViewModel.simulation_collision_active) {
                                const hx = 50 + Math.max(0, Math.min(290, appViewModel.simulation_collision_x)) / 290 * (width - 100)
                                const hy = height - 42 - Math.max(0, Math.min(170, appViewModel.simulation_collision_y)) / 170 * (height - 110)
                                ctx.strokeStyle = "#FF5A5A"; ctx.lineWidth = 4; ctx.beginPath(); ctx.arc(hx, hy, 18, 0, Math.PI * 2); ctx.stroke()
                                ctx.beginPath(); ctx.moveTo(hx - 25, hy); ctx.lineTo(hx + 25, hy); ctx.moveTo(hx, hy - 25); ctx.lineTo(hx, hy + 25); ctx.stroke()
                                ctx.fillStyle = "#FF5A5A"; ctx.font = "bold 13px sans-serif"; ctx.fillText("FIRST CONTACT", hx + 24, hy - 20)
                            }
                        }
                    }
                    Connections { target: appViewModel; function onSimulation_changed() { simulationCanvas.requestPaint() } function onState_changed() { simulationCanvas.requestPaint() } }
                }
                Rectangle { Layout.preferredWidth: 260; Layout.fillHeight: true; color: window.palette.surface; radius: 10
                    // Keep the safety and evidence actions reachable at the
                    // default 980x680 simulator size.  The hazard history is
                    // deliberately bounded so it cannot consume this column.
                    ScrollView {
                        id: simulatorControlsScroll
                        anchors.fill: parent
                        anchors.margins: 14
                        clip: true
                        // Keep the content tied to this owned viewport.
                        contentWidth: simulatorControlsScroll.width
                        ScrollBar.vertical.policy: ScrollBar.AsNeeded
                        ColumnLayout { width: simulatorControlsScroll.width; spacing: 8
                        Label { text: "Authoritative plant"; color: window.palette.text; font.weight: Font.DemiBold }
                        Label { text: "Machine " + (appViewModel ? appViewModel.machine_position : "—"); color: window.palette.text; font.family: "Cascadia Mono" }
                        Label { text: "Work " + (appViewModel ? appViewModel.work_position : "—"); color: window.palette.text; font.family: "Cascadia Mono" }
                        Label { text: "GRBL " + (appViewModel ? appViewModel.grbl_state : "—"); color: window.palette.muted }
                        SecondaryButton { Layout.fillWidth: true; visible: appViewModel && appViewModel.simulation_active; text: "Hide simulator"; onClicked: simulationWindow.visible = false }
                        Label { text: appViewModel ? appViewModel.simulation_homing_status : "Homing switches: not commissioned"; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: appViewModel ? appViewModel.simulation_limit_status : "Limit inputs: unavailable while disconnected"; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: appViewModel ? appViewModel.simulation_estop_status : "E-stop: external safety cutoff required"; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { visible: appViewModel && appViewModel.simulation_active; text: "Simulation-only safety exercise (symbolic pins; no physical GPIO)"; color: window.palette.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        RowLayout { visible: appViewModel && appViewModel.simulation_active; Layout.fillWidth: true; spacing: 5
                            SecondaryButton { Layout.fillWidth: true; text: "Assert reset E-stop"; onClicked: appViewModel.inject_simulation_estop(true, false) }
                            SecondaryButton { Layout.fillWidth: true; text: "Assert feedback E-stop"; onClicked: appViewModel.inject_simulation_estop(false, false) }
                        }
                        RowLayout { visible: appViewModel && appViewModel.simulation_active; Layout.fillWidth: true; spacing: 5
                            SecondaryButton { Layout.fillWidth: true; text: "Release E-stop"; onClicked: appViewModel.release_simulation_estop() }
                            SecondaryButton { Layout.fillWidth: true; text: "Acknowledge after reference"; enabled: appViewModel && appViewModel.simulation_estop_recovery_ready; onClicked: appViewModel.acknowledge_simulation_estop() }
                        }
                        RowLayout { visible: appViewModel && appViewModel.simulation_active; Layout.fillWidth: true; spacing: 8
                            Label { text: "Twin switches (checked = actuated):"; color: window.palette.muted }
                            ModernCheckBox { text: "X"; palette: window.palette; checked: appViewModel && appViewModel.simulation_limit_x; onClicked: appViewModel.inject_simulation_limit("X", checked) }
                            ModernCheckBox { text: "Y"; palette: window.palette; checked: appViewModel && appViewModel.simulation_limit_y; onClicked: appViewModel.inject_simulation_limit("Y", checked) }
                            ModernCheckBox { text: "Z"; palette: window.palette; checked: appViewModel && appViewModel.simulation_limit_z; onClicked: appViewModel.inject_simulation_limit("Z", checked) }
                        }
                        Label { visible: appViewModel && appViewModel.simulation_active; text: "The twin applies each axis's declared NC/NO polarity."; color: window.palette.subtle; font.pixelSize: 10; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: appViewModel ? appViewModel.simulation_auto_xyz_status : "Auto XYZ calibration plate: unavailable"; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        SecondaryButton { Layout.fillWidth: true; visible: appViewModel && appViewModel.simulation_active && !appViewModel.simulation_plate_commissioned; text: "Commission simulation Auto XYZ plate"; onClicked: appViewModel.commission_simulation_calibration_plate() }
                        SecondaryButton { Layout.fillWidth: true; visible: appViewModel && appViewModel.simulation_active; text: "Preview Auto XYZ calibration plate (commissioning required)"; enabled: appViewModel && appViewModel.simulation_auto_xyz_available; onClicked: autoXyzDialog.open() }
                        Label { text: "Stock metrics " + (appViewModel ? appViewModel.simulation_stock_metrics_json : "{}"); color: window.palette.muted; font.family: "Cascadia Mono"; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: "Safety state: " + (appViewModel ? appViewModel.simulation_collision_state : "Clear"); color: appViewModel && appViewModel.simulation_hazard_active ? window.palette.danger : window.palette.success; font.weight: Font.DemiBold; wrapMode: Text.Wrap }
                        Label { text: "Kind: " + (appViewModel ? appViewModel.simulation_collision_kind : "—"); color: window.palette.text; visible: appViewModel && appViewModel.simulation_hazard_active; wrapMode: Text.Wrap }
                        Label { text: "Bodies: " + (appViewModel ? appViewModel.simulation_collision_body : "—"); color: window.palette.text; visible: appViewModel && appViewModel.simulation_hazard_active; wrapMode: Text.Wrap }
                        Label { text: "Point: " + (appViewModel ? appViewModel.simulation_collision_point : "—"); color: window.palette.text; visible: appViewModel && appViewModel.simulation_hazard_active; font.family: "Cascadia Mono"; wrapMode: Text.Wrap }
                        Label { text: appViewModel ? appViewModel.simulation_collision_message : ""; color: window.palette.danger; visible: appViewModel && appViewModel.simulation_hazard_active; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: "Hazards"; color: window.palette.text; font.weight: Font.DemiBold }
                        ListView { Layout.fillWidth: true; Layout.preferredHeight: 120; Layout.minimumHeight: 72; model: appViewModel ? appViewModel.simulation_hazards : []; clip: true; delegate: Label { width: parent.width; text: "• " + modelData; color: window.palette.danger; wrapMode: Text.Wrap } }
                        Label { text: appViewModel ? appViewModel.simulation_export_status : ""; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        SecondaryButton { Layout.fillWidth: true; text: "Export evidence…"; enabled: appViewModel && appViewModel.simulation_export_available; onClicked: simulationEvidenceDialog.open() }
                        SecondaryButton { Layout.fillWidth: true; text: "Disconnect digital twin"; enabled: appViewModel && appViewModel.simulation_active; onClicked: appViewModel.disconnect() }
                        }
                    }
                }
            }
        }
    }

    Dialog {
        id: autoXyzDialog
        modal: true
        title: "Auto XYZ calibration — DIGITAL TWIN ONLY"
        width: Math.min(760, window.width - 48)
        height: Math.min(560, window.usableContentHeight - 24)
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.usableContentHeight - height) / 2)
        standardButtons: Dialog.NoButton
        onOpened: if (appViewModel && transportCombo.currentText === "USB serial") appViewModel.refresh_ports()
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }
        ColumnLayout { anchors.fill: parent; anchors.margins: 20; spacing: 10
            Label { text: "Commissioned conductive corner-circle fixture"; color: window.palette.text; font.pixelSize: 18; font.weight: Font.DemiBold }
            Label { text: appViewModel ? appViewModel.simulation_auto_xyz_status : "Unavailable"; color: window.palette.accent; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { text: "Interior seed pose (machine mm)"; color: window.palette.muted }
            GridLayout { columns: 6; Layout.fillWidth: true; columnSpacing: 8
                Label { text: "X"; color: window.palette.subtle }
                TextField { id: autoXyzSeedX; text: "20"; validator: DoubleValidator { bottom: 0; top: 290 } }
                Label { text: "Y"; color: window.palette.subtle }
                TextField { id: autoXyzSeedY; text: "20"; validator: DoubleValidator { bottom: 0; top: 170 } }
                Label { text: "Z"; color: window.palette.subtle }
                TextField { id: autoXyzSeedZ; text: "30"; validator: DoubleValidator { bottom: 0; top: 40 } }
            }
            Label { text: "Bounded plan: " + (appViewModel ? appViewModel.simulation_auto_xyz_plan : "Unavailable"); color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true; maximumLineCount: 5; elide: Text.ElideRight }
            Label { text: "State: " + (appViewModel ? appViewModel.auto_xyz_calibration_state : "idle"); color: window.palette.text }
            Item { Layout.fillHeight: true }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                Button { text: "Start Auto XYZ"; enabled: appViewModel && appViewModel.simulation_auto_xyz_available && !appViewModel.simulation_auto_xyz_active; onClicked: appViewModel.start_auto_xyz_calibration(Number(autoXyzSeedX.text), Number(autoXyzSeedY.text), Number(autoXyzSeedZ.text)) }
                Button { text: "Abort"; enabled: appViewModel && appViewModel.simulation_auto_xyz_active; onClicked: appViewModel.abort_auto_xyz_calibration() }
                Button { text: "Close"; onClicked: autoXyzDialog.close() }
            }
        }
    }

    CommissioningDialog {
        id: commissioningDialog
        appPalette: window.palette
        onOpenZProbeWizard: { commissioningDialog.close(); zProbeWizard.open() }
    }

    ZProbeWizard {
        id: zProbeWizard
        appPalette: window.palette
        onContinueToCommissioning: { zProbeWizard.close(); commissioningDialog.open() }
    }

    ZProbeResultDialog {
        id: zProbeResultDialog
        objectName: "zProbeResultDialog"
        appPalette: window.palette
        dialogWidth: window.width
        dialogHeight: window.usableContentHeight
        onContinueRequested: function(transactionId) { if (appViewModel) appViewModel.continue_z_probe_to_surface(transactionId) }
        onDismissed: function(transactionKey, backendSessionId) {
            window.zProbeDismissedTransactionKey = transactionKey
            window.zProbeDismissedBackendSession = backendSessionId
        }
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
                    engravingDialog.close(); window.selectGuidedStep(4)
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
            window.selectGuidedStep(4)
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
                                SecondaryButton { Layout.fillWidth: true; text: "Load bundled showcase STEP"; enabled: appViewModel && !appViewModel.step_importing; onClicked: appViewModel.load_bundled_showcase_step() }
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
        id: axesEditor
        objectName: "axesEditor"
        property var axisDraft: ({})
        modal: true
        title: "Axes / limits"
        width: 920
        height: Math.min(590, window.usableContentHeight - 24)
        x: Math.round((window.width - width) / 2)
        y: Math.max(12, Math.round((window.usableContentHeight - height) / 2))
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }
        function value(axis, key, fallback) {
            const item = axisDraft[axis]
            return item && item[key] !== undefined ? item[key] : fallback
        }
        function setValue(axis, key, value) {
            const next = {}
            for (const name in axisDraft) next[name] = axisDraft[name]
            const item = {}
            const current = axisDraft[axis] || {}
            for (const name in current) item[name] = current[name]
            item[key] = value
            next[axis] = item
            axisDraft = next
        }
        onOpened: {
            try { axisDraft = JSON.parse(appViewModel ? appViewModel.homing_limit_declarations_json : "{}") }
            catch (error) { axisDraft = ({}) }
        }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 18; spacing: 10
            Label { text: "Axes, travel, homing, and limits"; color: window.palette.text; font.pixelSize: 17; font.weight: Font.DemiBold }
            Label { text: "Changes use the guarded declaration save path. No axis moves occur while editing."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { text: appViewModel ? appViewModel.profile_summary : ""; color: window.palette.subtle; wrapMode: Text.Wrap; Layout.fillWidth: true }
            GridLayout { columns: 8; Layout.fillWidth: true; columnSpacing: 6; rowSpacing: 6
                Label { text: "Axis"; color: window.palette.subtle }
                Label { text: "Switch"; color: window.palette.subtle }
                Label { text: "End"; color: window.palette.subtle }
                Label { text: "Pin"; color: window.palette.subtle }
                Label { text: "Polarity"; color: window.palette.subtle }
                Label { text: "Hard limit"; color: window.palette.subtle }
                Label { text: "Debounce ms"; color: window.palette.subtle }
                Label { text: "Max override"; color: window.palette.subtle }
                Repeater { model: ["X", "Y", "Z"]
                    delegate: RowLayout { Layout.columnSpan: 8; spacing: 6
                        required property string modelData
                        Label { text: modelData; color: window.palette.text; Layout.preferredWidth: 26 }
                        CheckBox { objectName: "axisSwitch" + modelData; checked: axesEditor.value(modelData, "enabled", false); onToggled: axesEditor.setValue(modelData, "enabled", checked) }
                        ComboBox { objectName: "axisEnd" + modelData; model: ["min", "max"]; currentIndex: axesEditor.value(modelData, "end", "min") === "max" ? 1 : 0; onActivated: axesEditor.setValue(modelData, "end", currentText) }
                        TextField { objectName: "axisPin" + modelData; Layout.preferredWidth: 70; text: axesEditor.value(modelData, "pin", ""); onEditingFinished: axesEditor.setValue(modelData, "pin", text) }
                        CheckBox { objectName: "axisPolarity" + modelData; checked: axesEditor.value(modelData, "active_low", false); onToggled: axesEditor.setValue(modelData, "active_low", checked) }
                        CheckBox { objectName: "axisHardLimit" + modelData; checked: axesEditor.value(modelData, "hard_limit", false); onToggled: axesEditor.setValue(modelData, "hard_limit", checked) }
                        TextField {
                            objectName: "axisDebounce" + modelData
                            Layout.preferredWidth: 84
                            text: String(axesEditor.value(modelData, "debounce_ms", 5))
                            validator: DoubleValidator { bottom: 0; top: 1000 }
                            onEditingFinished: axesEditor.setValue(modelData, "debounce_ms", Number(text))
                        }
                        TextField {
                            objectName: "axisMax" + modelData
                            Layout.preferredWidth: 92
                            text: axesEditor.value(modelData, "max_override", null) === null ? "" : String(axesEditor.value(modelData, "max_override", ""))
                            validator: DoubleValidator { bottom: 0.001; top: 10000 }
                            onEditingFinished: axesEditor.setValue(modelData, "max_override", text === "" ? null : Number(text))
                        }
                    }
                }
            }
            Label { text: "Switches: enabled/end/pin/polarity/hard-limit/debounce/max override are shown for X, Y, and Z before saving."; color: window.palette.subtle; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Item { Layout.fillHeight: true }
            RowLayout { Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Cancel"; onClicked: axesEditor.close() }
            PrimaryButton { text: "Save axes / limits"; onClicked: { if (appViewModel.save_homing_limit_declarations(JSON.stringify(axesEditor.axisDraft))) axesEditor.close() } }
            }
        }
    }

    Dialog {
        id: probesEditor
        objectName: "probesEditor"
        property bool zPlate: false
        property bool toolSetter: false
        property bool movableXyz: false
        property bool fixedXyz: false
        property bool zActiveLow: false
        modal: true
        title: "Probes / safety"
        width: 720
        height: Math.min(680, window.usableContentHeight - 24)
        x: Math.round((window.width - width) / 2)
        y: Math.max(12, Math.round((window.usableContentHeight - height) / 2))
        standardButtons: Dialog.NoButton
        background: Rectangle { color: window.palette.surface; radius: 12; border.color: window.palette.divider; border.width: 1 }
        onOpened: {
            zPlate = appViewModel && appViewModel.movable_z_probe_enabled
            toolSetter = appViewModel && appViewModel.fixed_tool_setter_enabled
            movableXyz = appViewModel && appViewModel.movable_xyz_probe_enabled
            fixedXyz = appViewModel && appViewModel.fixed_xyz_probe_enabled
            zActiveLow = appViewModel && appViewModel.z_touch_plate_active_low
        }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 18; spacing: 9
            Label { text: "Probes and safety declarations"; color: window.palette.text; font.pixelSize: 17; font.weight: Font.DemiBold }
            Label { text: "Every schema probe kind is visible. Unsupported physical workflows remain configured but inert; only the digital-twin Auto XYZ and commissioned movable Z routes can act."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            ModernCheckBox { objectName: "probeMovableZ"; palette: window.palette; text: "Movable Z touch plate / puck (supported after commissioning)"; checked: probesEditor.zPlate; onToggled: probesEditor.zPlate = checked }
            ModernCheckBox { objectName: "probeFixedToolSetter"; palette: window.palette; text: "Fixed tool setter (configured — workflow unavailable)"; checked: probesEditor.toolSetter; onToggled: probesEditor.toolSetter = checked }
            ModernCheckBox { objectName: "probeMovableXyz"; palette: window.palette; text: "Movable physical XYZ (configured — workflow unavailable)"; checked: probesEditor.movableXyz; onToggled: probesEditor.movableXyz = checked }
            ModernCheckBox { objectName: "probeFixedXyz"; palette: window.palette; text: "Fixed XYZ (configured — workflow unavailable)"; checked: probesEditor.fixedXyz; onToggled: probesEditor.fixedXyz = checked }
            Divider {}
            Label { text: "Movable Z geometry, feed, and tolerance"; color: window.palette.text; font.weight: Font.DemiBold; visible: probesEditor.zPlate }
            GridLayout { columns: 2; Layout.fillWidth: true; columnSpacing: 10; rowSpacing: 6; visible: probesEditor.zPlate
                Label { text: "Plate thickness (mm)"; color: window.palette.muted }
                Field { id: setupPlateThickness; Layout.fillWidth: true; text: appViewModel ? String(appViewModel.z_touch_plate_thickness) : "19.37"; validator: DoubleValidator { bottom: 0.001; top: 100 } }
                Label { text: "Fast feed (mm/min)"; color: window.palette.muted }
                Field { id: setupPlateFastFeed; Layout.fillWidth: true; text: appViewModel ? String(appViewModel.z_touch_plate_fast_feed) : "100"; validator: DoubleValidator { bottom: 1; top: 1500 } }
                Label { text: "Slow feed (mm/min)"; color: window.palette.muted }
                Field { id: setupPlateSlowFeed; Layout.fillWidth: true; text: appViewModel ? String(appViewModel.z_touch_plate_slow_feed) : "25"; validator: DoubleValidator { bottom: 1; top: 1500 } }
                Label { text: "Search distance (mm)"; color: window.palette.muted }
                Field { id: setupPlateSearch; Layout.fillWidth: true; text: appViewModel ? String(appViewModel.z_touch_plate_max_search) : "5"; validator: DoubleValidator { bottom: 0.1; top: 100 } }
                Label { text: "Retract / clearance (mm)"; color: window.palette.muted }
                Field { id: setupPlateRetract; Layout.fillWidth: true; text: appViewModel ? String(appViewModel.z_touch_plate_retract) : "2"; validator: DoubleValidator { bottom: 0.1; top: 100 } }
                Label { text: "Final safe retract (mm)"; color: window.palette.muted }
                Field { id: setupPlateSafeRetract; Layout.fillWidth: true; text: appViewModel ? String(appViewModel.z_touch_plate_safe_retract) : "2"; validator: DoubleValidator { bottom: 0.1; top: 100 } }
                Label { text: "Repeatability tolerance (mm)"; color: window.palette.muted }
                Field { id: setupPlateTolerance; Layout.fillWidth: true; text: appViewModel ? String(appViewModel.z_touch_plate_tolerance) : "0.05"; validator: DoubleValidator { bottom: 0.001; top: 10 } }
            }
            ModernCheckBox { objectName: "probeActiveLow"; palette: window.palette; visible: probesEditor.zPlate; checked: probesEditor.zActiveLow; onToggled: probesEditor.zActiveLow = checked; text: "Invert probe input polarity in GRBL ($6)" }
            Label { text: appViewModel ? ("Current movable Z status: " + appViewModel.z_touch_plate_status_text) : ""; color: window.palette.muted; visible: probesEditor.zPlate; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Item { Layout.fillHeight: true }
            RowLayout { Layout.fillWidth: true
                SecondaryButton { text: "Open input test / commissioning"; enabled: probesEditor.zPlate; onClicked: { probesEditor.close(); commissioningDialog.open() } }
                Item { Layout.fillWidth: true }
                SecondaryButton { text: "Cancel"; onClicked: probesEditor.close() }
                PrimaryButton { objectName: "saveProbeDeclarations"; text: "Save probe declarations"; onClicked: { if (appViewModel.save_probe_configuration(probesEditor.zPlate, probesEditor.toolSetter, probesEditor.movableXyz, probesEditor.fixedXyz, Number(setupPlateThickness.text), probesEditor.zActiveLow, Number(setupPlateFastFeed.text), Number(setupPlateSlowFeed.text), Number(setupPlateSearch.text), Number(setupPlateRetract.text), Number(setupPlateSafeRetract.text), Number(setupPlateTolerance.text))) probesEditor.close() } }
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
                SecondaryButton { text: "Load bundled showcase STEP"; enabled: appViewModel && !appViewModel.step_importing; onClicked: appViewModel.load_bundled_showcase_step() }
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
                                        radius: 8; color: window.palette.raised; border.color: window.palette.divider; border.width: 1
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
                 PrimaryButton { text: "Generate and load"; enabled: appViewModel && appViewModel.step_loaded && !appViewModel.step_importing && appViewModel.step_preview_valid; onClicked: { appViewModel.create_step(modeCombo.currentText, orientationCombo.currentText, Number(stockWidthField.text), Number(stockHeightField.text), zeroLocationCombo.currentText, Number(toolDiameterField.text), Number(stepDepthField.text), Number(stepPassesField.text), Number(stockThicknessField.text), Number(breakthroughField.text), Number(tabCountField.text), Number(tabWidthField.text), Number(tabHeightField.text), Number(stepSafeField.text), Number(stepCutField.text), Number(stepPlungeField.text), Number(stepRpmField.text), Number(stepMaxStepdownField.text)); stepDialog.close(); window.selectGuidedStep(4) } }
            }
        }
    }

    PlatformDialogs.FileDialog {
        id: gcodeFileDialog
        title: "Load existing job"
        nameFilters: ["CNC jobs (*.nc *.gcode *.tap *.cnc *.txt *.json)", "All files (*.*)"]
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
        id: simulationEvidenceDialog
        title: "Export digital-twin evidence"
        fileMode: PlatformDialogs.FileDialog.SaveFile
        nameFilters: ["JSON evidence (*.json)", "All files (*.*)"]
        onAccepted: appViewModel.export_simulation_evidence(selectedFile)
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
        radius: 16
        border.color: Qt.rgba(1, 1, 1, 0.10)
        border.width: 1
    }

    component Divider: Rectangle {
        Layout.fillWidth: true
        height: 1
        color: window.palette.divider
    }

    component SectionTitle: Label {
        font.pixelSize: 20
        font.weight: Font.DemiBold
        font.letterSpacing: -0.2
        color: window.palette.text
    }

    component MutedLabel: Label {
        Layout.fillWidth: true
        color: window.palette.muted
        font.pixelSize: 13
        lineHeight: 1.15
        wrapMode: Text.Wrap
    }

    component Pill: Rectangle {
        required property string label
        required property color tone
        implicitWidth: pillLabel.implicitWidth + 18
        implicitHeight: 24
        radius: 12
        color: Qt.rgba(tone.r, tone.g, tone.b, 0.13)
        border.color: Qt.rgba(tone.r, tone.g, tone.b, 0.32)
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
        property string disabledReason: "This action is unavailable right now. Complete the required earlier step or restore the machine connection."
        implicitHeight: 40
        padding: 16
        font.pixelSize: 13
        font.weight: Font.DemiBold
        contentItem: Text {
            text: control.text
            color: control.enabled ? "white" : window.palette.subtle
            font: control.font
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 10
            opacity: control.enabled ? 1 : 0.48
            color: control.down ? (control.dangerous ? "#B94343" : "#086FCC")
                                : control.hovered ? (control.dangerous ? "#E26A6A" : window.palette.accentHover)
                                                  : (control.dangerous ? window.palette.danger : window.palette.accent)
            border.width: control.activeFocus ? 2 : 0
            border.color: "white"
            Behavior on color { ColorAnimation { duration: 120 } }
        }
        MouseArea {
            parent: Overlay.overlay
            x: control.mapToItem(Overlay.overlay, 0, 0).x
            y: control.mapToItem(Overlay.overlay, 0, 0).y
            width: control.width; height: control.height
            visible: control.visible && !control.enabled
            hoverEnabled: true; acceptedButtons: Qt.NoButton
            ToolTip.visible: containsMouse; ToolTip.delay: 350
            ToolTip.text: control.disabledReason
        }
    }

    component SecondaryButton: Button {
        id: control
        property string disabledReason: "This action is unavailable right now. Complete the required earlier step or restore the machine connection."
        implicitHeight: 38
        padding: 14
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
            radius: 10
            opacity: control.enabled ? 1 : 0.46
            color: control.down ? window.palette.elevated : control.hovered ? window.palette.hover : window.palette.raised
            border.width: control.activeFocus ? 2 : 1
            border.color: control.activeFocus ? window.palette.accent : Qt.rgba(1, 1, 1, 0.10)
            Behavior on color { ColorAnimation { duration: 120 } }
        }
        MouseArea {
            parent: Overlay.overlay
            x: control.mapToItem(Overlay.overlay, 0, 0).x
            y: control.mapToItem(Overlay.overlay, 0, 0).y
            width: control.width; height: control.height
            visible: control.visible && !control.enabled
            hoverEnabled: true; acceptedButtons: Qt.NoButton
            ToolTip.visible: containsMouse; ToolTip.delay: 350
            ToolTip.text: control.disabledReason
        }
    }

    component JogArrowButton: Button {
        id: jogControl
        property string glyph: ""
        property bool fine: false
        property string disabledReason: "Jogging requires a connected machine reporting Idle with a current position. Home the machine first when a trusted reference is required."
        padding: 3
        font.pixelSize: fine ? 15 : 13
        font.weight: Font.DemiBold
        activeFocusOnTab: true
        Accessible.name: "Jog " + glyph.replace("\n", " ")
        Accessible.description: fine ? "Move 0.1 millimeter" : "Press and hold for live jog"
        onActiveFocusChanged: if (!activeFocus && down && appViewModel) appViewModel.stop_live_jog()
        onVisibleChanged: if (!visible && down && appViewModel) appViewModel.stop_live_jog()
        Component.onDestruction: if (down && appViewModel) appViewModel.stop_live_jog()
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
            radius: jogControl.fine ? 9 : 14
            color: jogControl.down ? window.palette.accent : jogControl.hovered ? window.palette.hover : window.palette.raised
            border.width: jogControl.activeFocus ? 2 : 1
            border.color: jogControl.activeFocus ? window.palette.accentHover : jogControl.down ? window.palette.accentHover : Qt.rgba(1, 1, 1, jogControl.enabled ? 0.12 : 0.05)
            Behavior on color { ColorAnimation { duration: 100 } }
        }
        MouseArea {
            parent: Overlay.overlay
            x: jogControl.mapToItem(Overlay.overlay, 0, 0).x
            y: jogControl.mapToItem(Overlay.overlay, 0, 0).y
            width: jogControl.width; height: jogControl.height
            visible: jogControl.visible && !jogControl.enabled
            hoverEnabled: true; acceptedButtons: Qt.NoButton
            ToolTip.visible: containsMouse; ToolTip.delay: 350
            ToolTip.text: jogControl.disabledReason
        }
    }

    component Field: TextField {
        id: control
        implicitHeight: 38
        color: window.palette.text
        font.pixelSize: 13
        selectByMouse: true
        background: Rectangle {
            radius: 9
            color: window.palette.input
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
        height: 180
        color: Qt.rgba(window.palette.surface.r, window.palette.surface.g, window.palette.surface.b, 0.98)
        border.color: Qt.rgba(1, 1, 1, 0.08)
        border.width: 1

        ColumnLayout {
            anchors.fill: parent
            anchors.leftMargin: 24
            anchors.rightMargin: 24
            spacing: 4

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 42
                spacing: 16

                Row {
                    spacing: 9
                    Image { width: 26; height: 26; source: "../assets/pine-mark.svg"; fillMode: Image.PreserveAspectFit; anchors.verticalCenter: parent.verticalCenter }
                    Label { text: "Pine"; color: window.palette.text; font.pixelSize: 18; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                    Label { text: "CNC Studio"; color: window.palette.subtle; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                }
                Item { Layout.fillWidth: true }
                Pill { visible: appViewModel && appViewModel.header_status_visible; label: appViewModel ? appViewModel.header_status_text : ""; tone: appViewModel && appViewModel.safety_attention ? window.palette.warning : window.palette.danger }
                RowLayout { visible: appViewModel && appViewModel.job_active; spacing: 5
                    SecondaryButton { objectName: "pauseJob"; visible: appViewModel && appViewModel.job_state !== "Paused"; text: "Pause"; onClicked: appViewModel.pause_job() }
                    SecondaryButton { objectName: "resumeJob"; visible: appViewModel && appViewModel.job_state === "Paused"; text: "Resume"; onClicked: appViewModel.resume_job() }
                    PrimaryButton { objectName: "abortJob"; text: "Abort"; dangerous: true; onClicked: appViewModel.abort_job() }
                }
                SecondaryButton { objectName: "showSimulator"; visible: appViewModel && appViewModel.simulation_active && appViewModel.expert_mode; text: "Show simulator"; onClicked: window.showSimulator() }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 44
                radius: 12
                color: window.palette.raised
                border.color: Qt.rgba(1, 1, 1, 0.08)
                border.width: 1
                RowLayout { anchors.fill: parent; anchors.margins: 4; spacing: 3
                    WorkspaceButton { objectName: "machineWorkspace"; text: "Machine"; checked: window.inMachineWorkspace; onClicked: window.selectGuidedStep(window.machineSetupStep) }
                    WorkspaceButton { objectName: "jobWorkspace"; text: "Job"; checked: window.guidedIndex >= 5 && !window.configureOpen; onClicked: window.selectGuidedStep(appViewModel && appViewModel.job_active ? 6 : 5) }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 42
                spacing: 8
                Label { objectName: "guidedStepReason"; Layout.fillWidth: true; text: appViewModel ? ((appViewModel.guided_step + ". " + appViewModel.guided_step_title) + " — " + appViewModel.guided_step_reason) : "Follow the guided operator flow."; color: window.palette.muted; font.pixelSize: 11; wrapMode: Text.WordWrap; verticalAlignment: Text.AlignVCenter }
                SecondaryButton { objectName: "guidedBack"; text: "Back"; enabled: appViewModel && appViewModel.guided_step > 0; onClicked: appViewModel.guided_back() }
                PrimaryButton { objectName: "guidedContinue"; visible: appViewModel && appViewModel.guided_step < 5; text: "Continue"; enabled: appViewModel && appViewModel.guided_step_ready; disabledReason: appViewModel ? appViewModel.guided_step_reason : "The current step is not ready."; onClicked: appViewModel.guided_continue() }
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

    component WorkspaceButton: Button {
        id: workspaceControl
        checkable: true
        Layout.fillWidth: true
        implicitHeight: 34
        padding: 12
        font.pixelSize: 12
        font.weight: Font.DemiBold
        activeFocusOnTab: true
        contentItem: Text {
            text: workspaceControl.text
            color: !workspaceControl.enabled ? window.palette.subtle : workspaceControl.checked ? "white" : window.palette.muted
            font: workspaceControl.font
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 9
            opacity: workspaceControl.enabled ? 1 : 0.58
            color: workspaceControl.down ? window.palette.accentHover : workspaceControl.checked ? window.palette.accent : workspaceControl.hovered ? window.palette.elevated : "transparent"
            border.width: workspaceControl.activeFocus ? 2 : 0
            border.color: window.palette.accentHover
            Behavior on color { ColorAnimation { duration: 140 } }
        }
        ToolTip.visible: hovered
        ToolTip.text: workspaceControl.Accessible.name
    }

    footer: Rectangle {
        height: 58
        color: Qt.rgba(window.palette.surface.r, window.palette.surface.g, window.palette.surface.b, 0.98)
        border.color: Qt.rgba(1, 1, 1, 0.08)
        border.width: 1
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 24
            anchors.rightMargin: 24
            spacing: 22
            StatusMetric { name: "Machine"; value: appViewModel ? appViewModel.machine_position : "X—  Y—  Z—"; tone: window.palette.text }
            StatusMetric { name: "Work"; value: appViewModel ? appViewModel.work_position : "X—  Y—  Z—"; tone: window.palette.text }
            StatusMetric { name: "Reference"; value: appViewModel ? appViewModel.reference : "Position unknown"; tone: window.palette.warning }
            StatusMetric { name: "Work zero"; value: appViewModel ? appViewModel.work_zero : "Not confirmed"; tone: window.palette.warning }
            Item { Layout.fillWidth: true }
            StatusMetric { name: "Spindle"; value: appViewModel ? appViewModel.spindle : "Off"; tone: window.palette.muted }
            SecondaryButton { objectName: "connectionUtility"; text: appViewModel && appViewModel.connected ? "Connection…" : "Recover…"; onClicked: connectionDialog.open() }
            SecondaryButton { objectName: "guidedStep4"; text: "CAM tools…"; checkable: true; checked: window.guidedIndex === 4 && !window.configureOpen; onClicked: window.selectGuidedStep(4) }
            SecondaryButton { objectName: "configureUtility"; checkable: true; checked: window.configureOpen || window.guidedIndex === 0; text: "Configure"; onClicked: window.openConfigure() }
            SecondaryButton { objectName: "consoleUtility"; visible: appViewModel && appViewModel.expert_mode; text: "Console"; onClicked: consoleDialog.open() }
        }
    }

    IssueBanner {
        id: issueBanner
        objectName: "issueBanner"
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
        currentIndex: window.effectiveContentIndex

        // Configure — persistent machine definition and commissioning
        Item {
            id: setupPage
            objectName: "setupPage"
            property int sectionIndex: 0
            Panel {
                objectName: "guidedStepContentConfigure"
                anchors.fill: parent
                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 18
                    clip: true
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: setupPage.width - 36
                        spacing: 14
                        SectionTitle { text: "Configure" }
                        Label {
                            text: "Machine definition, safety declarations, commissioning, and the digital twin live here. Review this first-time or periodic configuration before connecting."
                            color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true
                        }
                        RowLayout { Layout.fillWidth: true; spacing: 6
                            Button { objectName: "setupSection0"; text: "Machine / Profile"; checkable: true; checked: setupPage.sectionIndex === 0; implicitHeight: 34; Layout.fillWidth: true; onClicked: setupPage.sectionIndex = 0; contentItem: Text { text: parent.text; color: parent.checked ? window.palette.text : window.palette.muted; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight } background: Rectangle { radius: 6; color: parent.checked ? Qt.rgba(window.palette.accent.r, window.palette.accent.g, window.palette.accent.b, 0.22) : window.palette.raised; border.color: parent.checked ? window.palette.accent : window.palette.divider; border.width: 1 } }
                            Button { objectName: "setupSection1"; text: "Axes / Limits"; checkable: true; checked: setupPage.sectionIndex === 1; implicitHeight: 34; Layout.fillWidth: true; onClicked: setupPage.sectionIndex = 1; contentItem: Text { text: parent.text; color: parent.checked ? window.palette.text : window.palette.muted; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight } background: Rectangle { radius: 6; color: parent.checked ? Qt.rgba(window.palette.accent.r, window.palette.accent.g, window.palette.accent.b, 0.22) : window.palette.raised; border.color: parent.checked ? window.palette.accent : window.palette.divider; border.width: 1 } }
                            Button { objectName: "setupSection2"; text: "Probes / Safety"; checkable: true; checked: setupPage.sectionIndex === 2; implicitHeight: 34; Layout.fillWidth: true; onClicked: setupPage.sectionIndex = 2; contentItem: Text { text: parent.text; color: parent.checked ? window.palette.text : window.palette.muted; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight } background: Rectangle { radius: 6; color: parent.checked ? Qt.rgba(window.palette.accent.r, window.palette.accent.g, window.palette.accent.b, 0.22) : window.palette.raised; border.color: parent.checked ? window.palette.accent : window.palette.divider; border.width: 1 } }
                            Button { objectName: "setupSection3"; text: "Commissioning"; checkable: true; checked: setupPage.sectionIndex === 3; implicitHeight: 34; Layout.fillWidth: true; onClicked: setupPage.sectionIndex = 3; contentItem: Text { text: parent.text; color: parent.checked ? window.palette.text : window.palette.muted; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight } background: Rectangle { radius: 6; color: parent.checked ? Qt.rgba(window.palette.accent.r, window.palette.accent.g, window.palette.accent.b, 0.22) : window.palette.raised; border.color: parent.checked ? window.palette.accent : window.palette.divider; border.width: 1 } }
                            Button { objectName: "setupSection4"; text: "Digital Twin"; checkable: true; checked: setupPage.sectionIndex === 4; implicitHeight: 34; Layout.fillWidth: true; onClicked: setupPage.sectionIndex = 4; contentItem: Text { text: parent.text; color: parent.checked ? window.palette.text : window.palette.muted; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight } background: Rectangle { radius: 6; color: parent.checked ? Qt.rgba(window.palette.accent.r, window.palette.accent.g, window.palette.accent.b, 0.22) : window.palette.raised; border.color: parent.checked ? window.palette.accent : window.palette.divider; border.width: 1 } }
                        }
                        Rectangle {
                            id: setupMachineSection
                            objectName: "setupMachineSection"
                            visible: setupPage.sectionIndex === 0
                            Layout.fillWidth: true; Layout.preferredHeight: 230; radius: 10
                            color: window.palette.raised; border.color: window.palette.divider; border.width: 1
                            ColumnLayout { anchors.fill: parent; anchors.margins: 14; spacing: 6
                                RowLayout { Layout.fillWidth: true
                                    Label { text: "Machine and profile"; color: window.palette.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                                    Item { Layout.fillWidth: true }
                                    Pill { label: appViewModel ? appViewModel.machine_id : "No profile"; tone: window.palette.muted }
                                }
                                Label { text: appViewModel ? appViewModel.profile_summary : "Select a machine profile and verify its usable travel."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                RowLayout { Layout.fillWidth: true
                                    SecondaryButton { objectName: "editProfile"; text: "Edit profile"; onClicked: profileDialog.open() }
                                    Label { text: "Machine selection is available from the profile editor."; color: window.palette.subtle; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.Wrap }
                                }
                                Divider {}
                                Label { text: "Connection defaults"; color: window.palette.text; font.weight: Font.DemiBold }
                                RowLayout { Layout.fillWidth: true
                                    ComboBox { id: configTransport; Layout.preferredWidth: 140; model: ["Wi-Fi TCP", "USB serial"]; currentIndex: appViewModel && appViewModel.preferred_transport === "USB serial" ? 1 : 0 }
                                    Field { id: configWifiHost; visible: configTransport.currentText === "Wi-Fi TCP"; Layout.fillWidth: true; text: appViewModel ? appViewModel.saved_wifi_host : ""; placeholderText: "Controller host" }
                                    Field { id: configWifiPort; visible: configTransport.currentText === "Wi-Fi TCP"; Layout.preferredWidth: 72; text: appViewModel ? String(appViewModel.saved_wifi_port) : "23"; validator: IntValidator { bottom: 1; top: 65535 } }
                                    Field { id: configUsbPort; visible: configTransport.currentText === "USB serial"; Layout.fillWidth: true; text: appViewModel ? appViewModel.saved_usb_port : ""; placeholderText: "COM port" }
                                    SecondaryButton { objectName: "saveConnectionDefaults"; text: "Save"; enabled: appViewModel && !appViewModel.connected; disabledReason: "Disconnect before changing connection defaults."; onClicked: appViewModel.save_connection_defaults(configTransport.currentText, configWifiHost.text, Number(configWifiPort.text), configUsbPort.text) }
                                }
                                Label { text: "Connect uses these saved values automatically; opening Configure never starts a connection."; color: window.palette.subtle; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            }
                        }
                        Rectangle {
                            id: setupAxesSection
                            objectName: "setupAxesSection"
                            visible: setupPage.sectionIndex === 1
                            Layout.fillWidth: true; Layout.preferredHeight: 460; radius: 10
                            color: window.palette.raised; border.color: window.palette.divider; border.width: 1
                            ColumnLayout { anchors.fill: parent; anchors.margins: 14; spacing: 6
                                Label { text: "Axes, travel, homing, and limits"; color: window.palette.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                                    Label { text: "Travel X/Y/Z: " + (appViewModel ? appViewModel.profile_x.toFixed(1) + " / " + appViewModel.profile_y.toFixed(1) + " / " + appViewModel.profile_z.toFixed(1) + " mm" : "—") + "   ·   Reference mode: " + (appViewModel ? appViewModel.workflow_reference_mode : "homing required"); color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                Label { objectName: "axisDeclarationX"; text: "X: " + window.axisDeclaration("X"); color: window.palette.text; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                Label { objectName: "axisDeclarationY"; text: "Y: " + window.axisDeclaration("Y"); color: window.palette.text; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                Label { objectName: "axisDeclarationZ"; text: "Z: " + window.axisDeclaration("Z"); color: window.palette.text; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                Repeater { model: appViewModel ? appViewModel.setup_warning_text : []
                                    delegate: Label { text: "⚠ " + modelData; color: window.palette.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                }
                                RowLayout { Layout.fillWidth: true
                                    SecondaryButton { objectName: "editAxesLimits"; text: "Edit axes and limits"; onClicked: axesEditor.open() }
                                    Label { text: "Guarded save preserves the current machine definition."; color: window.palette.subtle; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                }
                                Divider {}
                                Label { text: "Automatic travel envelope calibration"; color: window.palette.text; font.pixelSize: 14; font.weight: Font.DemiBold }
                                Label { text: "Homes each axis, advances in gentle bounded increments, then returns to the home switch to measure missed travel. Two matching detections and a bounded-overrun out-and-back validation are required. GRBL soft limits ($20) and configured hard-limit handling must be off; Pine still monitors every home input."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                RowLayout { Layout.fillWidth: true; spacing: 6
                                    Label { text: "Step"; color: window.palette.muted }
                                    Field { id: travelIncrement; Layout.preferredWidth: 58; text: "10"; validator: DoubleValidator { bottom: 1; top: 25 } }
                                    Label { text: "Overshoot"; color: window.palette.muted }
                                    Field { id: travelOvershoot; Layout.preferredWidth: 58; text: "30"; validator: DoubleValidator { bottom: 10; top: 100 } }
                                    Label { text: "Search feed"; color: window.palette.muted }
                                    Field { id: travelSearchFeed; Layout.preferredWidth: 62; text: "120"; validator: DoubleValidator { bottom: 10; top: 300 } }
                                    Label { text: "Return"; color: window.palette.muted }
                                    Field { id: travelReturnFeed; Layout.preferredWidth: 62; text: "600"; validator: DoubleValidator { bottom: 50; top: 1500 } }
                                }
                                Label { objectName: "travelCalibrationStatus"; text: appViewModel ? appViewModel.travel_calibration_status : "Travel calibration unavailable"; color: appViewModel && appViewModel.travel_calibration_can_accept ? window.palette.success : window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                ProgressBar { Layout.fillWidth: true; from: 0; to: 100; value: appViewModel ? Number(appViewModel.travel_calibration["progress"] || 0) : 0; visible: appViewModel && appViewModel.travel_calibration_active }
                                RowLayout { Layout.fillWidth: true
                                    PrimaryButton { objectName: "startTravelCalibration"; text: "Calibrate travel"; enabled: appViewModel && appViewModel.connected && appViewModel.can_home_machine && !appViewModel.travel_calibration_active; disabledReason: "Connect the machine, wait for fresh Idle, release all homing inputs, and turn the spindle off."; onClicked: appViewModel.start_travel_calibration(Number(travelIncrement.text), Number(travelOvershoot.text), Number(travelSearchFeed.text), Number(travelReturnFeed.text)) }
                                    SecondaryButton { objectName: "abortTravelCalibration"; text: "Abort"; enabled: appViewModel && appViewModel.travel_calibration_active; disabledReason: "No travel calibration is currently running."; onClicked: appViewModel.abort_travel_calibration() }
                                    PrimaryButton { objectName: "acceptTravelCalibration"; text: "Accept validated limits"; enabled: appViewModel && appViewModel.travel_calibration_can_accept; disabledReason: "All axes must have two matching detections and pass the final out-and-back validation."; onClicked: appViewModel.accept_travel_calibration() }
                                }
                            }
                        }
                        Rectangle {
                            id: setupProbeSection
                            objectName: "setupProbeSection"
                            visible: setupPage.sectionIndex === 2
                            Layout.fillWidth: true; Layout.preferredHeight: 278; radius: 10
                            color: window.palette.raised; border.color: window.palette.divider; border.width: 1
                            ColumnLayout { anchors.fill: parent; anchors.margins: 14; spacing: 6
                                Label { text: "Probes and safety"; color: window.palette.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                                Label { text: appViewModel ? appViewModel.machine_capabilities : "Capabilities unavailable"; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                Label { objectName: "probeDeclarationSummary"; text: "Movable Z: " + (appViewModel && appViewModel.movable_z_probe_enabled ? "enabled" : "disabled") + " · Fixed tool setter: " + (appViewModel && appViewModel.fixed_tool_setter_enabled ? "enabled / inert" : "disabled") + " · Movable XYZ: " + (appViewModel && appViewModel.movable_xyz_probe_enabled ? "enabled / inert" : "disabled") + " · Fixed XYZ: " + (appViewModel && appViewModel.fixed_xyz_probe_enabled ? "enabled / inert" : "disabled"); color: window.palette.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                Label { text: "Unsupported probe declarations remain configured and visibly inert until a supported workflow exists."; color: window.palette.subtle; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                RowLayout { Layout.fillWidth: true
                                    SecondaryButton { objectName: "editProbesSafety"; text: "Edit probes and safety"; onClicked: probesEditor.open() }
                                    SecondaryButton { objectName: "commissionMovableZ"; text: "Commission movable Z"; enabled: appViewModel && appViewModel.z_touch_plate_enabled; onClicked: commissioningDialog.open() }
                                    Label { text: "No-motion input test and supervised samples remain required."; color: window.palette.subtle; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                }
                            }
                        }
                        Rectangle {
                            id: setupCommissioningSection
                            objectName: "setupCommissioningSection"
                            visible: setupPage.sectionIndex === 3
                            Layout.fillWidth: true; Layout.preferredHeight: 112; radius: 10
                            color: window.palette.raised; border.color: window.palette.divider; border.width: 1
                            ColumnLayout { anchors.fill: parent; anchors.margins: 14; spacing: 6
                                Label { text: "Periodic commissioning"; color: window.palette.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                                Label { text: "Review readiness and repeat no-motion input checks whenever machine or probe configuration becomes stale."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                SecondaryButton { objectName: "openCommissioning"; text: "Open commissioning"; onClicked: commissioningDialog.open() }
                            }
                        }
                        Rectangle {
                            id: setupTwinSection
                            objectName: "setupTwinSection"
                            visible: setupPage.sectionIndex === 4
                            Layout.fillWidth: true; Layout.preferredHeight: 142; radius: 10
                            color: Qt.rgba(window.palette.accent.r, window.palette.accent.g, window.palette.accent.b, 0.08)
                            border.color: Qt.rgba(window.palette.accent.r, window.palette.accent.g, window.palette.accent.b, 0.38); border.width: 1
                            ColumnLayout { anchors.fill: parent; anchors.margins: 14; spacing: 6
                                RowLayout { Layout.fillWidth: true
                                    Label { text: "Digital twin"; color: window.palette.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                                    Item { Layout.fillWidth: true }
                                    Pill { label: "DIGITAL TWIN — NO PHYSICAL MACHINE"; tone: window.palette.accent }
                                }
                                Label { text: appViewModel && appViewModel.simulation_active ? "Active on loopback. Auto XYZ fixture and advanced validation are available for this session." : "Loopback-only controller twin; it never enumerates or contacts physical USB, Wi-Fi, GPIO, or COM endpoints."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                RowLayout { Layout.fillWidth: true
                                    SecondaryButton { objectName: "connectDigitalTwin"; text: "Connect digital twin"; visible: !(appViewModel && appViewModel.simulation_active); onClicked: connectionDialog.open() }
                                    SecondaryButton { text: "Commission Auto XYZ"; visible: appViewModel && appViewModel.simulation_active; enabled: appViewModel && !appViewModel.simulation_plate_commissioned; onClicked: appViewModel.commission_simulation_calibration_plate() }
                                    SecondaryButton { text: "Open advanced simulator"; visible: appViewModel && appViewModel.simulation_active; onClicked: window.showSimulator() }
                                }
                            }
                        }
                        Item { Layout.preferredHeight: 12 }
                    }
                }
            }
        }

        // Prepare
        Item {
            objectName: "guidedPreparePage"
            RowLayout { anchors.fill: parent; spacing: 14
                Panel { Layout.preferredWidth: 210; Layout.minimumWidth: 210; Layout.maximumWidth: 210; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 16; spacing: 10
                        SectionTitle { text: "Create or load" }
                        MutedLabel { text: "Start with an existing G-code file or create a centerline engraving." }
                        Divider {}
                        PrimaryButton { objectName: "loadGcode"; Layout.fillWidth: true; text: "Load G-code"; onClicked: gcodeFileDialog.open() }
                        SecondaryButton { Layout.fillWidth: true; text: "Engraving designer"; onClicked: engravingDialog.open() }
                        SecondaryButton { Layout.fillWidth: true; visible: appViewModel && appViewModel.expert_mode; text: "Guided STEP setup"; onClicked: stepWizardDialog.open() }
                        SecondaryButton { Layout.fillWidth: true; visible: appViewModel && appViewModel.expert_mode; text: "Advanced STEP / 2.5D"; onClicked: stepDialog.open() }
                        Item { Layout.fillHeight: true }
                        Label { text: "Generated jobs are validated before they can run."; color: window.palette.subtle; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
                Panel { objectName: "guidedStepContentPrepare"; Layout.fillWidth: true; Layout.fillHeight: true
                    ToolpathCanvas { anchors.fill: parent; anchors.margins: 18; modeLabel: "PREPARE" }
                }
                Panel { Layout.preferredWidth: 310; Layout.minimumWidth: 310; Layout.maximumWidth: 310; Layout.fillHeight: true
                    ColumnLayout { anchors.fill: parent; anchors.margins: 16; spacing: 13
                        SectionTitle { text: "Job inspector" }
                        MutedLabel { text: "Jobs loaded by Pine or an agent appear here. Large jobs may not have an in-app preview." }
                        Divider {}
                        Label { text: appViewModel ? appViewModel.job_file : "No job selected"; color: window.palette.text; font.pixelSize: 18; font.weight: Font.DemiBold; elide: Text.ElideMiddle; Layout.fillWidth: true }
                    MutedLabel { text: appViewModel ? appViewModel.job_summary : "Load G-code or create an engraving. The canvas remains the single source of visual context."; Layout.fillWidth: true }
                        Item { Layout.fillHeight: true }
                        SecondaryButton { Layout.fillWidth: true; text: "Save validated G-code"; enabled: appViewModel && appViewModel.job_file !== "No G-code loaded"; onClicked: saveGcodeDialog.open() }
                    }
                }
            }
        }

        // Job keeps one preview across review, preflight, and execution.
        Item {
            id: guidedRunPage
            objectName: "jobPage"
            property bool showCurrentLayer: true
            property bool showCuttingPath: true
            property bool showRapidPaths: true
            ColumnLayout { anchors.fill: parent; spacing: 8
                RowLayout { Layout.fillWidth: true
                    SectionTitle { text: "Job" }
                    Label { Layout.fillWidth: true; text: appViewModel ? appViewModel.job_file : ""; color: window.palette.muted; elide: Text.ElideMiddle }
                    SecondaryButton { objectName: "jobOpen"; text: "Open job…"; enabled: appViewModel && !appViewModel.job_active; onClicked: gcodeFileDialog.open() }
                    WorkspaceButton { objectName: "guidedStep5"; text: "Review"; checked: window.guidedIndex === 5; onClicked: window.selectGuidedStep(5) }
                    WorkspaceButton { objectName: "guidedStep6"; text: "Run"; checked: window.guidedIndex === 6; onClicked: window.selectGuidedStep(6) }
                }
                ColumnLayout {
                    objectName: "controllerRecovery"
                    Layout.fillWidth: true
                    property var recovery: appViewModel ? appViewModel.watchdog_recovery : ({})
                    property var continuation: appViewModel ? appViewModel.automatic_continuation : ({})
                    visible: Boolean(recovery.state && recovery.state !== "idle") || Boolean(continuation.enabled)
                    Label { text: parent.recovery.message || ""; visible: Boolean(text); color: window.palette.warning; Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText }
                    Label {
                        text: parent.continuation.message || (parent.continuation.enabled ? "Automatic continuation enabled for this job" : "")
                        visible: Boolean(text)
                        color: window.palette.muted; Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText
                    }
                    SecondaryButton { text: "Continue to guarded home"; visible: parent.recovery.state === "ready"; enabled: Boolean(parent.recovery.can_continue_to_home); Layout.fillWidth: true; onClicked: appViewModel.continue_watchdog_home() }
                    SecondaryButton { text: "Cancel recovery"; visible: Boolean(parent.recovery.can_cancel); Layout.fillWidth: true; onClicked: appViewModel.cancel_watchdog_recovery() }
                    SecondaryButton { text: "Open connection choices"; visible: parent.recovery.state === "failed" && appViewModel && !appViewModel.connected; Layout.fillWidth: true; onClicked: connectionDialog.open() }
                }
                RowLayout { Layout.fillWidth: true; Layout.fillHeight: true; spacing: 14
                    Panel { Layout.fillWidth: true; Layout.fillHeight: true
                        ToolpathCanvas {
                            objectName: "jobPreview"
                            anchors.fill: parent; anchors.margins: 18
                            modeLabel: window.guidedIndex === 6 ? "RUN" : "REVIEW"; showJob: true
                            showCurrentLayer: window.guidedIndex === 6 && guidedRunPage.showCurrentLayer
                            showCuttingPath: window.guidedIndex !== 6 || guidedRunPage.showCuttingPath
                            showRapidPaths: window.guidedIndex !== 6 || guidedRunPage.showRapidPaths
                        }
                    }
                    StackLayout { Layout.preferredWidth: 355; Layout.minimumWidth: 355; Layout.maximumWidth: 355; Layout.fillHeight: true
                        currentIndex: window.guidedIndex === 6 ? 1 : 0
                    Item { objectName: "guidedReviewPage"
                Panel { objectName: "guidedReviewContent"; anchors.fill: parent
                    ScrollView { anchors.fill: parent; anchors.margins: 18; clip: true; contentWidth: availableWidth
                        ColumnLayout { width: parent.width; spacing: 13
                            SectionTitle { text: "Review" }
                            Label { objectName: "guidedStepContentReview"; text: "Review the loaded job and its validation facts. When the preview is unavailable, inspect the job's separate review evidence."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Pill { label: appViewModel && appViewModel.review_facts.validation === "passed" ? "Envelope check passed" : "Validation not complete"; tone: appViewModel && appViewModel.review_facts.validation === "passed" ? window.palette.success : window.palette.warning }
                            Label { text: appViewModel ? appViewModel.job_file : "No job selected"; color: window.palette.text; font.pixelSize: 16; font.weight: Font.DemiBold; elide: Text.ElideMiddle; Layout.fillWidth: true }
                            MutedLabel { text: appViewModel ? appViewModel.job_summary : "Open a G-code file or Pine review bundle."; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            Rectangle { objectName: "jobProvenance"; Layout.fillWidth: true; implicitHeight: provenanceContent.implicitHeight + 18; radius: 10; color: Qt.rgba(window.palette.accent.r, window.palette.accent.g, window.palette.accent.b, 0.07); border.color: window.palette.subtle; border.width: 1
                                ColumnLayout { id: provenanceContent; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 9; spacing: 5
                                    Label { text: "Setup & provenance"; color: window.palette.text; font.pixelSize: 13; font.weight: Font.DemiBold }
                                    Label { visible: appViewModel && Boolean(appViewModel.job_provenance.setup_name); text: appViewModel ? "Reported setup: " + (appViewModel.job_provenance.setup_name || "") : ""; color: window.palette.text; Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText }
                                    Label { objectName: "setupMachineMismatch"; visible: appViewModel && Boolean(appViewModel.job_provenance.setup_machine_id) && appViewModel.job_provenance.setup_machine_id !== appViewModel.machine_id; text: appViewModel ? "This setup names machine profile " + (appViewModel.job_provenance.setup_machine_id || "") + ". Check the selected machine before running." : ""; color: window.palette.warning; Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText }
                                    Label { objectName: "jobProvenanceReport"; text: appViewModel && appViewModel.job_provenance.report_state === "matched" ? ("Matched report · " + appViewModel.job_provenance.report_name) : (appViewModel && appViewModel.job_provenance.notice ? appViewModel.job_provenance.notice : "No matching review report"); color: window.palette.muted; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true; textFormat: Text.PlainText }
                                    Label { visible: appViewModel && Boolean(appViewModel.job_provenance.bundle); text: appViewModel ? ("Bundle: " + appViewModel.job_provenance.bundle) : ""; color: window.palette.muted; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true; textFormat: Text.PlainText }
                                    Label { visible: appViewModel && Boolean(appViewModel.job_provenance.release_status); text: appViewModel ? ("Report status: " + appViewModel.job_provenance.release_status) : ""; color: window.palette.warning; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true; textFormat: Text.PlainText }
                                    Label { visible: appViewModel && (appViewModel.job_provenance.header_notes || []).length > 0; text: "G-code header notes"; color: window.palette.text; font.pixelSize: 11; font.weight: Font.DemiBold }
                                    Repeater { model: appViewModel ? (appViewModel.job_provenance.header_notes || []) : []
                                        delegate: Label { text: modelData; color: window.palette.muted; font.pixelSize: 10; wrapMode: Text.Wrap; Layout.fillWidth: true; textFormat: Text.PlainText }
                                    }
                                    Label { objectName: "jobGcodeSha256"; visible: appViewModel && Boolean(appViewModel.job_provenance.file_sha256); text: appViewModel ? ("Loaded G-code SHA-256: " + appViewModel.job_provenance.file_sha256) : ""; color: window.palette.muted; font.pixelSize: 10; wrapMode: Text.Wrap; Layout.fillWidth: true; textFormat: Text.PlainText }
                                    Repeater { model: appViewModel ? (appViewModel.job_provenance.details || []) : []
                                        delegate: Label { text: modelData; color: window.palette.muted; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true; textFormat: Text.PlainText }
                                    }
                                    Label { visible: appViewModel && Boolean(appViewModel.job_provenance.verification_text); text: appViewModel ? appViewModel.job_provenance.verification_text : ""; color: window.palette.success; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true; textFormat: Text.PlainText }
                                    Label { text: appViewModel && appViewModel.job_provenance.report_state === "matched" ? "Reported setup details are tied to these file bytes; they do not verify physical setup." : "Setup values stay unknown until a matching report supplies them."; color: window.palette.subtle; font.pixelSize: 10; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                }
                            }
                            Divider {}
                            Label { text: appViewModel ? ("Validation: " + appViewModel.review_facts.validation + " · collision: " + appViewModel.review_facts.collision_analysis + " · supervisor: " + appViewModel.review_facts.supervisor) : "Validation facts unavailable"; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { objectName: "reviewPhysicalSafetyFacts"; text: appViewModel ? ("Independent E-stop: " + appViewModel.review_facts.physical_safety_input + " · hazardous-power evidence: " + appViewModel.review_facts.physical_power_removal) : "Independent safety facts unavailable"; color: appViewModel && appViewModel.review_facts.physical_safety_clear ? window.palette.success : window.palette.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Repeater { model: ["Fresh Idle controller state", "Trusted machine reference", "Confirmed work zero", "Envelope validation passed"]
                                delegate: RowLayout { Layout.fillWidth: true; spacing: 8
                                    property bool passed: index === 0 ? (appViewModel && appViewModel.review_facts.fresh_status) : index === 1 ? (appViewModel && appViewModel.reference_trusted) : index === 2 ? (appViewModel && appViewModel.work_zero_confirmed) : (appViewModel && appViewModel.review_facts.bounds_checked)
                                    Rectangle { width: 17; height: 17; radius: 8.5; color: parent.passed ? Qt.rgba(window.palette.success.r, window.palette.success.g, window.palette.success.b, 0.18) : "transparent"; border.color: parent.passed ? window.palette.success : window.palette.subtle; border.width: 1; Label { anchors.centerIn: parent; text: parent.parent.passed ? "✓" : ""; color: window.palette.success; font.bold: true } }
                                    Label { text: modelData; color: parent.passed ? window.palette.text : window.palette.muted; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.Wrap }
                                }
                            }
                            Item { Layout.fillHeight: true }
                            PrimaryButton { objectName: "acknowledgeReview"; visible: window.guidedIndex === 5; Layout.fillWidth: true; text: appViewModel && appViewModel.review_acknowledged ? "Review acknowledged" : "Acknowledge review"; enabled: appViewModel && !appViewModel.review_acknowledged && appViewModel.workflow_steps[5].state === "required"; onClicked: { appViewModel.acknowledge_review(); if (appViewModel.review_acknowledged) appViewModel.guided_continue() } }
                        }
                    }
                }
                    }
                    Item { objectName: "guidedRunPage"
                Panel { objectName: "guidedRunContent"; anchors.fill: parent
                    ScrollView { anchors.fill: parent; anchors.margins: 18; clip: true; contentWidth: availableWidth
                        ColumnLayout { width: parent.width; spacing: 13
                            Rectangle { objectName: "runSafetyAttention"; visible: appViewModel && appViewModel.safety_attention; Layout.fillWidth: true; implicitHeight: runAttentionText.implicitHeight + 18; radius: 10; color: Qt.rgba(window.palette.warning.r, window.palette.warning.g, window.palette.warning.b, 0.14); border.color: window.palette.warning; border.width: 1
                                Label { id: runAttentionText; anchors.fill: parent; anchors.margins: 9; text: appViewModel ? appViewModel.safety_attention_text : "Safety attention required"; color: window.palette.warning; wrapMode: Text.Wrap; verticalAlignment: Text.AlignVCenter }
                            }
                            SectionTitle { text: "Run" }
                            Label { objectName: "guidedStepContentRun"; text: "Complete the physical preflight, then use the guarded execution controls. Essential recovery remains available while running."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            ColumnLayout { objectName: "runPlotLayerControls"; visible: window.guidedIndex === 6 && appViewModel && appViewModel.job_file !== "No G-code loaded"; Layout.fillWidth: true; spacing: 2
                                Label { text: "Plot layers"; color: window.palette.text; font.pixelSize: 13; font.weight: Font.DemiBold }
                                ModernCheckBox { objectName: "showCurrentLayer"; Layout.fillWidth: true; palette: window.palette; text: "Current cutting layer"; checked: guidedRunPage.showCurrentLayer; onToggled: guidedRunPage.showCurrentLayer = checked }
                                ModernCheckBox { objectName: "showCuttingPath"; Layout.fillWidth: true; palette: window.palette; text: "Cutting paths"; checked: guidedRunPage.showCuttingPath; onToggled: guidedRunPage.showCuttingPath = checked }
                                ModernCheckBox { objectName: "showRapidPaths"; Layout.fillWidth: true; palette: window.palette; text: "Rapid move paths"; checked: guidedRunPage.showRapidPaths; onToggled: guidedRunPage.showRapidPaths = checked }
                            }
                            Rectangle { objectName: "runTravelCalibration"; visible: appViewModel && (appViewModel.travel_calibration_active || appViewModel.travel_calibration_can_accept); Layout.fillWidth: true; implicitHeight: calibrationRunContent.implicitHeight + 24; radius: 12; color: Qt.rgba(window.palette.accent.r, window.palette.accent.g, window.palette.accent.b, 0.12); border.color: window.palette.accent; border.width: 1
                                ColumnLayout { id: calibrationRunContent; anchors.fill: parent; anchors.margins: 12; spacing: 8
                                    Label { text: "Travel envelope calibration"; color: window.palette.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                                    Label { text: appViewModel ? appViewModel.travel_calibration_status : "Calibration status unavailable"; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    ProgressBar { Layout.fillWidth: true; from: 0; to: 100; value: appViewModel ? Number(appViewModel.travel_calibration["progress"] || 0) : 0 }
                                    RowLayout { Layout.fillWidth: true
                                        SecondaryButton { text: "Abort calibration"; enabled: appViewModel && appViewModel.travel_calibration_active; disabledReason: "Calibration is no longer running."; onClicked: appViewModel.abort_travel_calibration() }
                                        Item { Layout.fillWidth: true }
                                        PrimaryButton { text: "Accept calibrated limits"; enabled: appViewModel && appViewModel.travel_calibration_can_accept; disabledReason: "All axes must pass repeated detection and final validation first."; onClicked: appViewModel.accept_travel_calibration() }
                                    }
                                }
                            }
                            Pill { label: appViewModel && appViewModel.review_facts.validation === "passed" ? "Envelope check passed" : "Validation not complete"; tone: appViewModel && appViewModel.review_facts.validation === "passed" ? window.palette.success : window.palette.warning }
                            Divider {}
                            Label { text: appViewModel && appViewModel.job_active ? (appViewModel.job_state.toLowerCase() === "draining" ? "All commands accepted · waiting for physical motion to finish" : appViewModel.job_state + " · " + appViewModel.job_progress + "% commands accepted") : (appViewModel && appViewModel.next_part_available ? "Job complete" : "Ready when verified"); color: window.palette.text; font.pixelSize: 18; font.weight: Font.DemiBold; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            RowLayout { Layout.fillWidth: true
                                Label { text: "Nominal CAM duration"; color: window.palette.muted; font.pixelSize: 12 }
                                Label { text: appViewModel ? appViewModel.job_estimate : "—"; color: window.palette.text; font.pixelSize: 12 }
                                Item { Layout.fillWidth: true }
                                Label { visible: appViewModel && appViewModel.job_active; text: appViewModel ? ("Nominal plan left: " + appViewModel.job_time_remaining) : ""; color: window.palette.accent; font.pixelSize: 12; font.weight: Font.DemiBold }
                            }
                            Label { visible: appViewModel && appViewModel.job_active; text: appViewModel ? "Observed active time: " + appViewModel.job_elapsed + " · physical ETA unavailable until motion-position tracking is calibrated" : ""; color: window.palette.muted; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { visible: appViewModel && appViewModel.job_active; text: appViewModel && appViewModel.review_facts.fresh_status && appViewModel.feed !== "—" ? "Controller-reported feed: " + appViewModel.feed + " mm/min" : "Controller-reported feed: unavailable"; color: window.palette.muted; font.pixelSize: 12 }
                            Rectangle { objectName: "jobRecoveryBookmark"; visible: appViewModel && appViewModel.job_recovery && appViewModel.job_recovery["state"] !== "none" && appViewModel.job_recovery["state"] !== "complete"; Layout.fillWidth: true; implicitHeight: recoveryBookmarkColumn.implicitHeight + 20; radius: 9; color: Qt.rgba(window.palette.warning.r, window.palette.warning.g, window.palette.warning.b, 0.10); border.color: window.palette.warning; border.width: 1
                                ColumnLayout { id: recoveryBookmarkColumn; anchors.fill: parent; anchors.margins: 10; spacing: 4
                                    Label { id: recoveryBookmarkText; text: appViewModel ? ("Recovery bookmark: " + (appViewModel.job_recovery["filename"] || "loaded job") + " · " + Number(appViewModel.job_recovery["accepted_commands"] || 0) + " of " + Number(appViewModel.job_recovery["total_commands"] || 0) + " commands accepted. This is review context, not a position-safe resume; home and restore work zero before preparing a restart.") : ""; color: window.palette.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    Label { objectName: "confirmedPauseBookmark"; visible: appViewModel && appViewModel.job_recovery && appViewModel.job_recovery["pause_bookmark"] ? appViewModel.job_recovery["pause_bookmark"]["confirmed"] === true : false; text: {
                                        if (!appViewModel || !appViewModel.job_recovery) return ""
                                        var bookmark = appViewModel.job_recovery["pause_bookmark"] || {}
                                        var tool = bookmark["tool_context"] || {}
                                        var reportedTools = tool["reported_tool_details"] || []
                                        var toolText = reportedTools.length ? reportedTools.join("; ") : "Tool not reported"
                                        var liveText = bookmark["live_hold_confirmed"] ? "fresh controller Hold confirmed on this backend session" : "Hold was confirmed earlier; confirm current machine state before continuing"
                                        var policyText = appViewModel.automatic_continuation.enabled ? "Automatic continuation is enabled for the exact job under its recovery policy." : "Automatic resume is disabled; after disconnect or restart, review the exact job hash, re-home, confirm work zero, and verify the installed tool and workholding."
                                        return "Pause bookmark: " + liveText + " at " + (bookmark["confirmed_at_utc"] || "an unrecorded time") + ". Tool context: " + toolText + ". " + policyText
                                    }
                                    color: window.palette.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                }
                            }
                            ProgressBar { Layout.fillWidth: true; from: 0; to: 100; value: appViewModel ? appViewModel.job_progress : 0; visible: appViewModel && appViewModel.review_facts.validation === "passed" }
                            MutedLabel { visible: appViewModel && appViewModel.job_active; text: "Progress counts commands accepted by the controller; buffered motion may still be running. Time estimates exclude acceleration and corner slowdowns."; Layout.fillWidth: true }
                            PineLiveCard { Layout.fillWidth: true; palette: window.palette }
                            Label { text: appViewModel ? ("Validation: " + appViewModel.review_facts.validation + " · collision: " + appViewModel.review_facts.collision_analysis + " · supervisor: " + appViewModel.review_facts.supervisor) : "Validation facts unavailable"; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { objectName: "runPhysicalSafetyFacts"; text: appViewModel ? ("Independent E-stop: " + appViewModel.review_facts.physical_safety_input + " · hazardous-power evidence: " + appViewModel.review_facts.physical_power_removal) : "Independent safety facts unavailable"; color: appViewModel && appViewModel.review_facts.physical_safety_clear ? window.palette.success : window.palette.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Repeater { model: ["Machine is connected and Idle", "Virtual reference is trusted", "XYZ work zero is confirmed", "Envelope validation passed"]
                                delegate: RowLayout { Layout.fillWidth: true; spacing: 8
                                    property bool passed: index === 0 ? (appViewModel && appViewModel.review_facts.fresh_status) : index === 1 ? (appViewModel && appViewModel.reference_trusted) : index === 2 ? (appViewModel && appViewModel.work_zero_confirmed) : (appViewModel && appViewModel.review_facts.bounds_checked)
                                    Rectangle { width: 17; height: 17; radius: 8.5; color: parent.passed ? Qt.rgba(window.palette.success.r, window.palette.success.g, window.palette.success.b, 0.18) : "transparent"; border.color: parent.passed ? window.palette.success : window.palette.subtle; border.width: 1; Label { anchors.centerIn: parent; text: parent.parent.passed ? "✓" : ""; color: window.palette.success; font.bold: true } }
                                    Label { text: modelData; color: parent.passed ? window.palette.text : window.palette.muted; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.Wrap }
                                }
                            }
                            ModernCheckBox { objectName: "physicalPreflight"; visible: window.guidedIndex === 6; Layout.fillWidth: true; palette: window.palette; text: "Material and tool are secure"; checked: appViewModel && appViewModel.guided_preflight_confirmed; onClicked: if (appViewModel) appViewModel.set_physical_preflight_confirmed(checked) }
                            Item { Layout.fillHeight: true }
                            PrimaryButton { objectName: "startJob"; visible: window.guidedIndex === 6; Layout.fillWidth: true; text: "Start job"; enabled: appViewModel && appViewModel.start_job_action_ready; disabledReason: appViewModel ? appViewModel.start_job_block_reason : "Job status is unavailable."; opacity: enabled ? 1 : 0.55; onClicked: appViewModel.start_job() }
                            Label { objectName: "startJobGateMessage"; visible: appViewModel && !appViewModel.start_job_action_ready; Layout.fillWidth: true; text: appViewModel ? appViewModel.start_job_block_reason : "Job status is unavailable."; color: window.palette.warning; font.pixelSize: 11; wrapMode: Text.Wrap }
                            SecondaryButton { objectName: "nextPart"; visible: window.guidedIndex === 6 && appViewModel && appViewModel.next_part_available; Layout.fillWidth: true; text: "Prepare next part"; onClicked: appViewModel.prepare_next_part() }
                            RowLayout { visible: appViewModel && appViewModel.expert_mode; Layout.fillWidth: true
                                SecondaryButton { objectName: "spindleOn"; Layout.fillWidth: true; text: "Spindle on"; enabled: appViewModel && appViewModel.can_jog; onClicked: appViewModel.start_spindle(12000) }
                                SecondaryButton { objectName: "spindleOff"; Layout.fillWidth: true; text: "Spindle off"; enabled: appViewModel && appViewModel.connected; onClicked: appViewModel.stop_spindle() }
                            }
                        }
                    }
                }
                    }
                    }
                }
            }
        }

        // Machine
        Item {
            id: machinePage
            objectName: "machinePage"
            property bool coordinatesExpanded: false
            RowLayout { anchors.fill: parent; spacing: 14
                Panel { id: guidedMachineContext; objectName: "guidedMachineContext"; Layout.preferredWidth: 355; Layout.minimumWidth: 300; Layout.fillHeight: true
                    ScrollView { anchors.fill: parent; anchors.margins: 18; clip: true; contentWidth: availableWidth
                        ColumnLayout { width: parent.width; spacing: 12
                            Rectangle { objectName: "machineSafetyAttention"; visible: appViewModel && appViewModel.safety_attention; Layout.fillWidth: true; implicitHeight: attentionContent.implicitHeight + 18; radius: 10; color: Qt.rgba(window.palette.warning.r, window.palette.warning.g, window.palette.warning.b, 0.14); border.color: window.palette.warning; border.width: 1
                                ColumnLayout { id: attentionContent; anchors.fill: parent; anchors.margins: 9; spacing: 6
                                    Label { id: attentionText; text: appViewModel ? appViewModel.safety_attention_text : "Safety attention required"; color: window.palette.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    Label { objectName: "physicalSafetyInputStatus"; visible: appViewModel && (appViewModel.physical_safety_input_commissioned || appViewModel.physical_safety_input_blocks_motion); text: appViewModel ? appViewModel.physical_safety_input_status_text : ""; color: window.palette.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    SecondaryButton { objectName: "acknowledgePhysicalSafetyInput"; visible: appViewModel && appViewModel.physical_safety_input_acknowledge_available; Layout.fillWidth: true; text: "Acknowledge released physical E-stop"; onClicked: appViewModel.acknowledge_physical_safety_input() }
                                }
                            }
                            SectionTitle { text: appViewModel ? appViewModel.profile_name : "Machine" }
                            MutedLabel { text: appViewModel && appViewModel.connected ? appViewModel.connection_text + " · " + appViewModel.grbl_state : "Controller disconnected"; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            MutedLabel { text: appViewModel && appViewModel.reference_trusted ? "Machine reference trusted" : "Machine reference unconfirmed"; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            MutedLabel { text: appViewModel && appViewModel.work_zero_confirmed ? "Current XYZ work zero confirmed" : "Current XYZ work zero unconfirmed"; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            MutedLabel { visible: window.guidedIndex !== 3 && appViewModel && appViewModel.saved_work_zero_display_available; text: appViewModel ? appViewModel.saved_work_zero_text : ""; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            MutedLabel { visible: appViewModel && appViewModel.job_file && appViewModel.job_file !== "No G-code loaded"; text: appViewModel ? "Job: " + appViewModel.job_file : ""; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            Label { visible: appViewModel && Boolean(appViewModel.job_provenance.setup_name); text: appViewModel ? "Reported job setup: " + (appViewModel.job_provenance.setup_name || "") : ""; color: window.palette.muted; Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText }
                            RowLayout { Layout.fillWidth: true; spacing: 3
                                WorkspaceButton { Layout.fillWidth: true; objectName: "guidedStep1"; text: "Connect"; checked: window.guidedIndex === 1 && !window.configureOpen; enabled: true; Accessible.name: "Connect step"; onClicked: window.selectGuidedStep(1) }
                                WorkspaceButton { Layout.fillWidth: true; objectName: "guidedStep2"; text: "Home"; checked: window.guidedIndex === 2 && !window.configureOpen; enabled: true; Accessible.name: "Home step"; onClicked: window.selectGuidedStep(2) }
                                WorkspaceButton { Layout.fillWidth: true; objectName: "guidedStep3"; text: "Work Zero"; checked: window.guidedIndex === 3 && !window.configureOpen; enabled: true; Accessible.name: "Work Zero step"; onClicked: window.selectGuidedStep(3) }
                            }
                            MutedLabel { text: appViewModel ? appViewModel.guided_step_reason : "Machine status unavailable."; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Divider {}
                            Rectangle { objectName: "guidedConnectContent"; visible: window.guidedIndex === 1; Layout.fillWidth: true; Layout.preferredHeight: 150; radius: 9; color: window.palette.raised; border.color: window.palette.divider; border.width: 1
                                ColumnLayout { anchors.fill: parent; anchors.margins: 12; spacing: 7
                                    Label { text: "Connection"; color: window.palette.text; font.weight: Font.DemiBold }
                                    Label { text: appViewModel && appViewModel.connected ? appViewModel.connection_text : "Disconnected — choose a controller to begin."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    PrimaryButton { objectName: "connectStepAction"; Layout.fillWidth: true; text: "Open connection choices"; onClicked: connectionDialog.open() }
                                }
                            }
                            Rectangle { objectName: "guidedHomeContent"; visible: window.guidedIndex === 2; Layout.fillWidth: true; Layout.preferredHeight: 110; radius: 9; color: window.palette.raised; border.color: window.palette.divider; border.width: 1
                                ColumnLayout { anchors.fill: parent; anchors.margins: 12; spacing: 6
                                    Label { text: "Home machine"; color: window.palette.text; font.weight: Font.DemiBold }
                                    Label { text: appViewModel ? appViewModel.workflow_steps[2].reason : "Home the machine before setting work zero."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                }
                            }
                            Rectangle { objectName: "guidedWorkZeroContent"; visible: window.guidedIndex === 3; Layout.fillWidth: true; Layout.preferredHeight: 155; radius: 9; color: window.palette.raised; border.color: window.palette.divider; border.width: 1
                                ColumnLayout { anchors.fill: parent; anchors.margins: 12; spacing: 6
                                    Label { text: "Work-zero methods"; color: window.palette.text; font.weight: Font.DemiBold }
                                    Label { text: appViewModel ? appViewModel.workflow_steps[3].reason : "Choose a guarded work-zero method."; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    Label { text: "Manual, configured movable-Z, or loopback-only Auto XYZ are shown when their gates are satisfied."; color: window.palette.subtle; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                }
                            }
                            SecondaryButton { visible: appViewModel && appViewModel.expert_mode; Layout.fillWidth: true; text: "Console…"; onClicked: consoleDialog.open() }
                            Item { Layout.fillHeight: true }
                            MutedLabel { text: "Use Continue after the current prerequisite is genuinely complete."; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        }
                    }
                }
                Panel { Layout.fillWidth: true; Layout.fillHeight: true
                    ToolpathCanvas { anchors.fill: parent; anchors.margins: 18; modeLabel: "MACHINE"; showEnvelope: true; interactiveMove: true }
                }
                Panel { objectName: "machineMotionPanel"; visible: window.guidedIndex === 2 || window.guidedIndex === 3; Layout.preferredWidth: visible ? 365 : 0; Layout.minimumWidth: visible ? 365 : 0; Layout.maximumWidth: visible ? 365 : 0; Layout.fillHeight: true
                    ScrollView { anchors.fill: parent; anchors.margins: 18; clip: true; contentWidth: availableWidth
                    ColumnLayout { width: parent.width; spacing: 12
                        PrimaryButton { objectName: "panelHomeMachineIcon"; visible: window.guidedIndex === 2; Layout.fillWidth: true; text: "Home machine"; enabled: appViewModel && appViewModel.can_home_machine; disabledReason: appViewModel ? appViewModel.home_action_block_reason : "Homing status is unavailable."; onClicked: appViewModel.home_machine() }
                        Label { objectName: "homeMachineGateMessage"; visible: window.guidedIndex === 2 && appViewModel && !appViewModel.can_home_machine; Layout.fillWidth: true; text: appViewModel ? appViewModel.home_action_block_reason : "Homing status is unavailable."; color: window.palette.warning; font.pixelSize: 11; wrapMode: Text.Wrap }
                        Label { objectName: "homeMachineStatus"; visible: window.guidedIndex === 2; text: appViewModel ? appViewModel.homing_status : "Home status unavailable"; color: appViewModel && appViewModel.homing_state === "failed" ? window.palette.danger : window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        SectionTitle { text: "Position the machine" }
                        MutedLabel { text: "Use small steps near the workpiece. Commands are ignored while GRBL is not Idle and are checked against the trusted envelope." }
                        RowLayout { Layout.fillWidth: true
                            Label { text: "Feed"; color: window.palette.muted; font.pixelSize: 12 }
                            Field { id: jogFeedField; Layout.preferredWidth: 78; text: "500"; validator: DoubleValidator { bottom: 1; top: 1500 } }
                            Label { text: "mm/min"; color: window.palette.subtle; font.pixelSize: 11 }
                            Item { Layout.fillWidth: true }
                        }
                        RowLayout { objectName: "jogPrecisionSelector"; Layout.fillWidth: true
                            Label { text: "Precision step"; color: window.palette.muted; font.pixelSize: 12 }
                            Item { Layout.fillWidth: true }
                            SecondaryButton { objectName: "jogStepSelectorPointOne"; text: (window.jogStep === 0.1 ? "✓  " : "") + "0.1 mm"; onClicked: window.jogStep = 0.1 }
                            SecondaryButton { objectName: "jogStepSelectorOne"; text: (window.jogStep === 1.0 ? "✓  " : "") + "1 mm"; onClicked: window.jogStep = 1.0 }
                        }
                        RowLayout { Layout.alignment: Qt.AlignHCenter; spacing: 12
                            Item {
                                id: xyJogPad
                                objectName: "xyJogPad"
                                width: 214
                                height: 214

                                Rectangle { anchors.fill: parent; radius: 18; color: "#1D2025"; border.color: window.palette.divider; border.width: 1 }
                                // One continuous, envelope-bounded jog per press. Release,
                                // pointer cancellation, focus loss, or destruction stops it.
                                JogArrowButton { objectName: "jogHoldYPlus"; x: 76; y: 6; width: 62; height: 42; glyph: "▲\nY+"; enabled: appViewModel && (appViewModel.can_live_jog || appViewModel.live_jog_active); disabledReason: appViewModel ? appViewModel.move_action_block_reason : "Jogging status is unavailable."; onPressed: appViewModel.start_live_jog("Y", 1); onReleased: appViewModel.stop_live_jog(); onCanceled: appViewModel.stop_live_jog() }
                                JogArrowButton { objectName: "jogHoldXMinus"; x: 7; y: 86; width: 58; height: 42; glyph: "◀\nX−"; enabled: appViewModel && (appViewModel.can_live_jog || appViewModel.live_jog_active); disabledReason: appViewModel ? appViewModel.move_action_block_reason : "Jogging status is unavailable."; onPressed: appViewModel.start_live_jog("X", -1); onReleased: appViewModel.stop_live_jog(); onCanceled: appViewModel.stop_live_jog() }
                                JogArrowButton { objectName: "jogHoldXPlus"; x: 149; y: 86; width: 58; height: 42; glyph: "▶\nX+"; enabled: appViewModel && (appViewModel.can_live_jog || appViewModel.live_jog_active); disabledReason: appViewModel ? appViewModel.move_action_block_reason : "Jogging status is unavailable."; onPressed: appViewModel.start_live_jog("X", 1); onReleased: appViewModel.stop_live_jog(); onCanceled: appViewModel.stop_live_jog() }
                                JogArrowButton { objectName: "jogHoldYMinus"; x: 76; y: 166; width: 62; height: 42; glyph: "▼\nY−"; enabled: appViewModel && (appViewModel.can_live_jog || appViewModel.live_jog_active); disabledReason: appViewModel ? appViewModel.move_action_block_reason : "Jogging status is unavailable."; onPressed: appViewModel.start_live_jog("Y", -1); onReleased: appViewModel.stop_live_jog(); onCanceled: appViewModel.stop_live_jog() }

                                SecondaryButton {
                                    objectName: "jogStepYPlus"
                                    x: 90; y: 53; width: 34; height: 26; padding: 1; font.pixelSize: 10
                                    text: "Y+"
                                    Accessible.name: "Single precision step Y plus"
                                    Accessible.description: "Move Y plus by " + Number(window.jogStep).toString() + " millimeters"
                                    onClicked: if (appViewModel) appViewModel.jog("Y", window.jogStep)
                                }
                                SecondaryButton {
                                    objectName: "jogStepXMinus"
                                    x: 68; y: 92; width: 34; height: 26; padding: 1; font.pixelSize: 10
                                    text: "X−"
                                    Accessible.name: "Single precision step X minus"
                                    Accessible.description: "Move X minus by " + Number(window.jogStep).toString() + " millimeters"
                                    onClicked: if (appViewModel) appViewModel.jog("X", -window.jogStep)
                                }
                                SecondaryButton {
                                    objectName: "jogStepXPlus"
                                    x: 112; y: 92; width: 34; height: 26; padding: 1; font.pixelSize: 10
                                    text: "X+"
                                    Accessible.name: "Single precision step X plus"
                                    Accessible.description: "Move X plus by " + Number(window.jogStep).toString() + " millimeters"
                                    onClicked: if (appViewModel) appViewModel.jog("X", window.jogStep)
                                }
                                SecondaryButton {
                                    objectName: "jogStepYMinus"
                                    x: 90; y: 132; width: 34; height: 26; padding: 1; font.pixelSize: 10
                                    text: "Y−"
                                    Accessible.name: "Single precision step Y minus"
                                    Accessible.description: "Move Y minus by " + Number(window.jogStep).toString() + " millimeters"
                                    onClicked: if (appViewModel) appViewModel.jog("Y", -window.jogStep)
                                }

                            }

                            ColumnLayout { objectName: "zJogControls"; Layout.alignment: Qt.AlignVCenter; spacing: 7
                                Label { text: "Z AXIS"; color: window.palette.subtle; font.pixelSize: 10; font.weight: Font.DemiBold; Layout.alignment: Qt.AlignHCenter }
                                JogArrowButton { objectName: "jogHoldZPlus"; Layout.preferredWidth: 76; Layout.preferredHeight: 47; glyph: "▲\nZ+"; enabled: appViewModel && (appViewModel.can_live_jog || appViewModel.live_jog_active); disabledReason: appViewModel ? appViewModel.move_action_block_reason : "Jogging status is unavailable."; onPressed: appViewModel.start_live_jog("Z", 1); onReleased: appViewModel.stop_live_jog(); onCanceled: appViewModel.stop_live_jog() }
                                RowLayout { objectName: "zPrecisionStepControls"; Layout.fillWidth: true; spacing: 4
                                    SecondaryButton { objectName: "jogStepZPlus"; Layout.preferredWidth: 34; Layout.preferredHeight: 26; padding: 1; font.pixelSize: 10; text: "Z+"; Accessible.name: "Single precision step Z plus"; Accessible.description: "Move Z plus by " + Number(window.jogStep).toString() + " millimeters"; onClicked: if (appViewModel) appViewModel.jog("Z", window.jogStep) }
                                    SecondaryButton { objectName: "jogStepZMinus"; Layout.preferredWidth: 34; Layout.preferredHeight: 26; padding: 1; font.pixelSize: 10; text: "Z−"; Accessible.name: "Single precision step Z minus"; Accessible.description: "Move Z minus by " + Number(window.jogStep).toString() + " millimeters"; onClicked: if (appViewModel) appViewModel.jog("Z", -window.jogStep) }
                                }
                                JogArrowButton { objectName: "jogHoldZMinus"; Layout.preferredWidth: 76; Layout.preferredHeight: 47; glyph: "▼\nZ−"; enabled: appViewModel && (appViewModel.can_live_jog || appViewModel.live_jog_active); disabledReason: appViewModel ? appViewModel.move_action_block_reason : "Jogging status is unavailable."; onPressed: appViewModel.start_live_jog("Z", -1); onReleased: appViewModel.stop_live_jog(); onCanceled: appViewModel.stop_live_jog() }
                            }
                        }
                        Label { Layout.alignment: Qt.AlignHCenter; text: "Hold to move · release to stop"; color: window.palette.muted; font.pixelSize: 11 }
                        Label { objectName: "jogGateMessage"; visible: appViewModel && !appViewModel.can_live_jog && !appViewModel.live_jog_active; Layout.fillWidth: true; text: appViewModel ? appViewModel.move_action_block_reason : "Jogging status is unavailable."; color: window.palette.warning; font.pixelSize: 11; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter }
                        Divider {}
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
                        SecondaryButton { objectName: "moveSafely"; visible: machinePage.coordinatesExpanded; Layout.fillWidth: true; text: "Move safely"; enabled: appViewModel && appViewModel.can_jog; disabledReason: appViewModel ? appViewModel.move_action_block_reason : "Positioning status is unavailable."; onClicked: appViewModel.move_to(Number(targetX.text), Number(targetY.text), Number(targetZ.text), Number(jogFeedField.text)) }
                        Label { objectName: "moveSafelyGateMessage"; visible: machinePage.coordinatesExpanded && appViewModel && !appViewModel.can_jog; Layout.fillWidth: true; text: appViewModel ? appViewModel.move_action_block_reason : "Positioning status is unavailable."; color: window.palette.warning; font.pixelSize: 11; wrapMode: Text.Wrap }
                        Divider {}
                        ColumnLayout { visible: window.guidedIndex === 3; Layout.fillWidth: true; spacing: 8
                            Label { text: "Choose one guarded work-zero method"; color: window.palette.subtle; font.pixelSize: 11; font.weight: Font.DemiBold }
                            Rectangle { objectName: "manualWorkZeroCard"; Layout.fillWidth: true; Layout.preferredHeight: 144; radius: 9; color: window.palette.raised; border.color: window.palette.divider; border.width: 1
                                ColumnLayout { anchors.fill: parent; anchors.margins: 10; spacing: 5
                                    RowLayout { Layout.fillWidth: true
                                        Label { text: "Manual XYZ"; color: window.palette.text; font.weight: Font.DemiBold }
                                        Item { Layout.fillWidth: true }
                                        Label { text: window.workflowMethod("manual_xyz").state; color: window.workflowMethod("manual_xyz").available ? window.palette.success : window.palette.warning }
                                    }
                                    Label { text: window.workflowMethod("manual_xyz").reason; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    GridLayout { Layout.fillWidth: true; columns: 4; columnSpacing: 5
                                        SecondaryButton { objectName: "manualZeroX"; Layout.fillWidth: true; text: "Zero X"; enabled: window.workflowMethod("manual_x").available; onClicked: appViewModel.set_work_zero("X") }
                                        SecondaryButton { objectName: "manualZeroY"; Layout.fillWidth: true; text: "Zero Y"; enabled: window.workflowMethod("manual_y").available; onClicked: appViewModel.set_work_zero("Y") }
                                        SecondaryButton { objectName: "manualZeroZ"; Layout.fillWidth: true; text: "Zero Z"; enabled: window.workflowMethod("manual_z").available; onClicked: appViewModel.set_work_zero("Z") }
                                        PrimaryButton { objectName: "manualZeroXYZ"; Layout.fillWidth: true; text: "Zero XYZ"; enabled: window.workflowMethod("manual_xyz").available; onClicked: appViewModel.set_work_zero("XYZ") }
                                    }
                                }
                            }
                            Rectangle { objectName: "movableZWorkZeroCard"; visible: appViewModel && appViewModel.z_touch_plate_enabled; Layout.fillWidth: true; Layout.preferredHeight: 170; radius: 9; color: window.palette.raised; border.color: window.palette.divider; border.width: 1
                                ColumnLayout { anchors.fill: parent; anchors.margins: 10; spacing: 5
                                    RowLayout { Layout.fillWidth: true
                                        Label { text: "Movable Z touch plate"; color: window.palette.text; font.weight: Font.DemiBold }
                                        Item { Layout.fillWidth: true }
                                        Label { text: window.workflowMethod("movable_z_plate").state; color: window.workflowMethod("movable_z_plate").available ? window.palette.success : window.palette.warning }
                                    }
                                    Label { text: window.workflowMethod("movable_z_plate").reason; color: window.palette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    Label { text: "Place a flat puck on the workpiece, attach the clip, and keep the spindle off. Remove the puck when the result dialog appears."; color: window.palette.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    RowLayout { Layout.fillWidth: true
                                        PrimaryButton { objectName: "probeWorkZ"; Layout.fillWidth: true; text: "Probe work Z"; enabled: appViewModel !== null; Accessible.description: window.workflowMethod("movable_z_plate").reason; onClicked: appViewModel.probe_work_z() }
                                        SecondaryButton { objectName: "abortProbe"; visible: appViewModel && appViewModel.probe_active; Layout.fillWidth: true; text: "Abort probe"; onClicked: appViewModel.abort_probe() }
                                        SecondaryButton { objectName: "testProbeInput"; text: "Test input…"; onClicked: zProbeWizard.open() }
                                    }
                                }
                            }
                        }
                        Rectangle {
                            objectName: "autoXyzWorkZeroCard"
                            visible: window.guidedIndex === 3 && appViewModel && appViewModel.simulation_active
                            Layout.fillWidth: true
                            Layout.preferredHeight: 154
                            radius: 10
                            color: Qt.rgba(window.palette.accent.r, window.palette.accent.g, window.palette.accent.b, 0.08)
                            border.color: Qt.rgba(window.palette.accent.r, window.palette.accent.g, window.palette.accent.b, 0.38)
                            border.width: 1
                            ColumnLayout { anchors.fill: parent; anchors.margins: 12; spacing: 6
                                RowLayout { Layout.fillWidth: true
                                    Label { text: "XYZ probe plate"; color: window.palette.text; font.weight: Font.DemiBold; font.pixelSize: 14 }
                                    Item { Layout.fillWidth: true }
                                    Pill { label: "DIGITAL TWIN"; tone: window.palette.accent }
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: appViewModel && appViewModel.simulation_active
                                          ? (appViewModel.simulation_plate_commissioned
                                             ? "Commissioned corner-circle fixture. The twin will find X/Y, touch Z, and confirm G54."
                                             : "Connect the Virtual Machine, commission the corner-circle fixture, then run bounded Auto XYZ.")
                                          : "Automated plate probing is currently simulation-only; physical commissioning is not enabled."
                                    color: window.palette.muted
                                    wrapMode: Text.Wrap
                                    font.pixelSize: 11
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: appViewModel ? appViewModel.simulation_auto_xyz_status : "Auto XYZ calibration plate unavailable"
                                    color: window.palette.subtle
                                    wrapMode: Text.Wrap
                                    font.pixelSize: 11
                                }
                                RowLayout { Layout.fillWidth: true; spacing: 7
                                    SecondaryButton {
                                        Layout.fillWidth: true
                                        visible: appViewModel && appViewModel.simulation_active && !appViewModel.simulation_plate_commissioned
                                        text: "Commission plate"
                                        onClicked: appViewModel.commission_simulation_calibration_plate()
                                    }
                                    PrimaryButton {
                                        Layout.fillWidth: true
                                        visible: appViewModel && appViewModel.simulation_active
                                        enabled: appViewModel && appViewModel.simulation_auto_xyz_available
                                        text: "Open Auto XYZ"
                                        onClicked: autoXyzDialog.open()
                                    }
                                }
                            }
                        }
                        Label {
                            objectName: "savedPreviousWorkZero"
                            visible: window.guidedIndex === 3 && appViewModel && appViewModel.saved_work_zero_display_available
                            Layout.fillWidth: true
                            text: appViewModel ? appViewModel.saved_work_zero_text : ""
                            color: window.palette.muted
                            wrapMode: Text.Wrap
                        }
                        SecondaryButton {
                            objectName: "returnWorkZero"
                            visible: window.guidedIndex === 3 && appViewModel && (appViewModel.saved_work_zero_available || appViewModel.work_zero_confirmed)
                            Layout.fillWidth: true
                            text: appViewModel && appViewModel.work_zero_confirmed ? "Return to confirmed work zero" : "Return to saved work zero"
                            enabled: appViewModel && appViewModel.can_jog
                            disabledReason: appViewModel ? appViewModel.move_action_block_reason : "Machine status is unavailable."
                            onClicked: appViewModel.return_to_work_zero()
                        }
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
        id: toolpathCanvas
        property string modeLabel: "PREVIEW"
        property bool showJob: false
        property bool showCurrentLayer: true
        property bool showCuttingPath: true
        property bool showRapidPaths: true
        property bool showEnvelope: false
        property bool interactiveMove: false
        property real selectedX: 0
        property real selectedY: 0
        property real selectedZ: 0
        property bool targetSelected: false

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
                const hasRasterPreview = appViewModel && appViewModel.preview_image_url.length > 0
                if (!hasStock && !hasRasterPreview) {
                    ctx.strokeStyle = "#4B5867"
                    ctx.lineWidth = 2
                    ctx.strokeRect(inset, inset, width - inset * 2, height - inset * 2)
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
                    ctx.lineWidth = 2.2; ctx.lineCap = "round"; ctx.lineJoin = "round"
                    const splitJobPaths = toolpathCanvas.showJob && appViewModel.preview_path_layers_available
                    const cuttingStrokes = splitJobPaths ? appViewModel.preview_cutting_strokes : appViewModel.preview_strokes
                    if (!toolpathCanvas.showJob || toolpathCanvas.showCuttingPath) {
                        ctx.strokeStyle = "#168BFF"
                        for (const stroke of cuttingStrokes) {
                            if (!stroke.length) continue
                            ctx.beginPath(); ctx.moveTo(offsetX + stroke[0][0] * scale, offsetY - stroke[0][1] * scale)
                            for (let index = 1; index < stroke.length; index++) ctx.lineTo(offsetX + stroke[index][0] * scale, offsetY - stroke[index][1] * scale)
                            ctx.stroke()
                        }
                    }
                    if (splitJobPaths && toolpathCanvas.showRapidPaths) {
                        ctx.strokeStyle = "#F2B84B"
                        for (const stroke of appViewModel.preview_rapid_strokes) {
                            if (!stroke.length) continue
                            ctx.beginPath(); ctx.moveTo(offsetX + stroke[0][0] * scale, offsetY - stroke[0][1] * scale)
                            for (let index = 1; index < stroke.length; index++) ctx.lineTo(offsetX + stroke[index][0] * scale, offsetY - stroke[index][1] * scale)
                            ctx.stroke()
                        }
                    }
                }
                if (!hasRasterPreview) {
                    ctx.fillStyle = "#40C4D9"
                    ctx.beginPath(); ctx.arc(workZeroX, workZeroY, 6, 0, Math.PI * 2); ctx.fill()
                }
            }
        }
        Image {
            id: largeJobRasterPreview
            objectName: "largeJobRasterPreview"
            visible: !toolpathCanvas.showEnvelope && appViewModel && appViewModel.preview_image_url.length > 0
                     && (!toolpathCanvas.showJob || !appViewModel.preview_path_layers_available)
            anchors.fill: canvas
            source: appViewModel ? appViewModel.preview_image_url : ""
            fillMode: Image.PreserveAspectFit
            cache: false
            smooth: false
            asynchronous: false
        }
        Image {
            id: largeJobRapidRasterPreview
            objectName: "largeJobRapidRasterPreview"
            visible: !toolpathCanvas.showEnvelope && toolpathCanvas.showJob && toolpathCanvas.showRapidPaths
                     && appViewModel && appViewModel.preview_path_layers_available
            anchors.fill: canvas
            source: appViewModel ? appViewModel.preview_rapid_image_url : ""
            fillMode: Image.PreserveAspectFit
            cache: false; smooth: false; asynchronous: false
        }
        Image {
            id: largeJobCuttingRasterPreview
            objectName: "largeJobCuttingRasterPreview"
            visible: !toolpathCanvas.showEnvelope && toolpathCanvas.showJob && toolpathCanvas.showCuttingPath
                     && appViewModel && appViewModel.preview_path_layers_available
            anchors.fill: canvas
            source: appViewModel ? appViewModel.preview_cutting_image_url : ""
            fillMode: Image.PreserveAspectFit
            cache: false; smooth: false; asynchronous: false
        }
        Canvas {
            id: jobExecutionOverlay
            anchors.fill: canvas
            visible: toolpathCanvas.showJob && appViewModel
            onPaint: {
                const ctx = getContext("2d")
                ctx.reset()
                if (!appViewModel) return
                const bounds = appViewModel.job_plot_bounds || {}
                const minX = Number(bounds["min_x"]), minY = Number(bounds["min_y"])
                const maxX = Number(bounds["max_x"]), maxY = Number(bounds["max_y"])
                if (!isFinite(minX) || !isFinite(minY) || !isFinite(maxX) || !isFinite(maxY) || maxX <= minX || maxY <= minY) return
                let left = 0, top = 0, drawW = width, drawH = height, padding = 0
                const splitRaster = toolpathCanvas.showJob && appViewModel.preview_path_layers_available
                const rasterForBounds = splitRaster ? largeJobCuttingRasterPreview : largeJobRasterPreview
                if ((rasterForBounds.visible || splitRaster) && appViewModel.preview_image_width > 0 && appViewModel.preview_image_height > 0) {
                    // jobExecutionOverlay is parented to ``canvas`` while the
                    // Image is parented to ToolpathCanvas. Convert its painted
                    // rect into this overlay's coordinate system exactly once.
                    // PreserveAspectFit centers its painted pixels inside the Image.
                    // ``x``/``y`` name the full Image item, not that painted rect.
                    left = rasterForBounds.x - canvas.x
                            + (rasterForBounds.width - rasterForBounds.paintedWidth) / 2
                    top = rasterForBounds.y - canvas.y
                           + (rasterForBounds.height - rasterForBounds.paintedHeight) / 2
                    drawW = rasterForBounds.paintedWidth; drawH = rasterForBounds.paintedHeight
                    padding = 12
                } else {
                    const inset = Math.min(width, height) * 0.13
                    left = inset; top = inset; drawW = width - 2 * inset; drawH = height - 2 * inset
                }
                const sourceW = Math.max(1, appViewModel.preview_image_width || drawW)
                const sourceH = Math.max(1, appViewModel.preview_image_height || drawH)
                // The backend rasterizer itself letterboxes the program bounds
                // inside a 12px-padded source image. Recreate that exact source
                // rectangle before mapping work coordinates onto displayed pixels.
                const spanX = maxX - minX, spanY = maxY - minY
                const sourceScale = Math.min((sourceW - 2 * padding) / spanX,
                                             (sourceH - 2 * padding) / spanY)
                const contentW = spanX * sourceScale, contentH = spanY * sourceScale
                const sourceOffsetX = (sourceW - contentW) / 2
                const sourceOffsetY = (sourceH - contentH) / 2
                const innerLeft = left + sourceOffsetX / sourceW * drawW
                const innerTop = top + sourceOffsetY / sourceH * drawH
                const innerW = Math.max(0.01, contentW / sourceW * drawW)
                const innerH = Math.max(0.01, contentH / sourceH * drawH)
                const toX = x => innerLeft + (x - minX) / (maxX - minX) * innerW
                const toY = y => innerTop + (maxY - y) / (maxY - minY) * innerH
                const layer = appViewModel.program_execution_layer || {}
                if (toolpathCanvas.showCurrentLayer && layer["state"] === "cutting_layer") {
                    ctx.strokeStyle = "#30D158"; ctx.lineWidth = 1.6; ctx.lineCap = "round"; ctx.lineJoin = "round"
                    const strokes = layer["strokes"] || []
                    for (const stroke of strokes) {
                        if (!stroke || stroke.length < 2) continue
                        ctx.beginPath(); ctx.moveTo(toX(Number(stroke[0][0])), toY(Number(stroke[0][1])))
                        for (let index = 1; index < stroke.length; index++) ctx.lineTo(toX(Number(stroke[index][0])), toY(Number(stroke[index][1])))
                        ctx.stroke()
                    }
                }
                const marker = appViewModel.live_work_marker || {}
                if (marker["visible"]) {
                    const x = toX(Number(marker["x"])), y = toY(Number(marker["y"]))
                    ctx.fillStyle = "#FF9F0A"; ctx.strokeStyle = "#F5F5F7"; ctx.lineWidth = 2
                    ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.fill(); ctx.stroke()
                }
            }
            Connections { target: appViewModel; function onPosition_changed() { jobExecutionOverlay.requestPaint() } function onState_changed() { jobExecutionOverlay.requestPaint() } function onPreview_changed() { jobExecutionOverlay.requestPaint() } }
        }
        property var liveMarker: appViewModel ? appViewModel.envelope_marker : ({})
        MouseArea {
            id: envelopePointer
            anchors.fill: canvas
            visible: parent.interactiveMove
            hoverEnabled: true
            cursorShape: appViewModel && appViewModel.can_jog && liveMarker && Boolean(liveMarker["known"])
                         ? Qt.CrossCursor : Qt.ArrowCursor
            onClicked: mouse => {
                if (!(appViewModel && appViewModel.can_jog && liveMarker && Boolean(liveMarker["known"])))
                    return
                const inset = Math.min(canvas.width, canvas.height) * 0.13
                const usableWidth = Math.max(1, canvas.width - inset * 2)
                const usableHeight = Math.max(1, canvas.height - inset * 2)
                const nx = Math.max(0, Math.min(1, (mouse.x - inset) / usableWidth))
                const ny = Math.max(0, Math.min(1, (canvas.height - inset - mouse.y) / usableHeight))
                toolpathCanvas.selectedX = nx * Number(appViewModel.profile_x)
                toolpathCanvas.selectedY = ny * Number(appViewModel.profile_y)
                toolpathCanvas.selectedZ = Number(liveMarker["z"])
                toolpathCanvas.targetSelected = true
                moveFromCanvasDialog.open()
            }
            ToolTip.visible: containsMouse && !(appViewModel && appViewModel.can_jog && liveMarker && Boolean(liveMarker["known"]))
            ToolTip.delay: 350
            ToolTip.text: "Direct positioning requires a connected, Idle machine with a current position. Home the machine to establish a trusted travel envelope."
        }
        Rectangle {
            visible: parent.interactiveMove && parent.targetSelected
            z: 3
            property real envelopeInset: Math.min(canvas.width, canvas.height) * 0.13
            width: 18; height: 18; radius: 9
            x: canvas.x + envelopeInset + (parent.selectedX / Math.max(0.001, Number(appViewModel && appViewModel.profile_x || 1))) * (canvas.width - envelopeInset * 2) - width / 2
            y: canvas.y + canvas.height - envelopeInset - (parent.selectedY / Math.max(0.001, Number(appViewModel && appViewModel.profile_y || 1))) * (canvas.height - envelopeInset * 2) - height / 2
            color: "transparent"; border.color: window.palette.success; border.width: 2
        }
        Dialog {
            id: moveFromCanvasDialog
            modal: true
            width: 460
            anchors.centerIn: Overlay.overlay
            title: "Move to selected point?"
            standardButtons: Dialog.Ok | Dialog.Cancel
            onAccepted: {
                appViewModel.move_to(toolpathCanvas.selectedX, toolpathCanvas.selectedY, toolpathCanvas.selectedZ, Number(jogFeedField.text))
                toolpathCanvas.targetSelected = false
            }
            onRejected: toolpathCanvas.targetSelected = false
            contentItem: Label {
                text: "Move safely to X " + toolpathCanvas.selectedX.toFixed(2)
                      + "  Y " + toolpathCanvas.selectedY.toFixed(2)
                      + " mm?\nZ remains at " + toolpathCanvas.selectedZ.toFixed(2)
                      + " mm. The guarded move planner will raise to safe Z before XY travel when needed."
                color: window.palette.text
                wrapMode: Text.Wrap
                width: 420
                padding: 16
            }
        }
        Rectangle {
            id: liveEnvelopeMarker
            objectName: "liveEnvelopeMarker"
            property real envelopeInset: Math.min(canvas.width, canvas.height) * 0.13
            visible: parent.showEnvelope && liveMarker && Boolean(liveMarker["visible"])
            width: 16; height: 16; radius: 8
            x: canvas.x + envelopeInset + Number(liveMarker && liveMarker.render_x || 0) * (canvas.width - envelopeInset * 2) - width / 2
            y: canvas.y + canvas.height - envelopeInset - Number(liveMarker && liveMarker.render_y || 0) * (canvas.height - envelopeInset * 2) - height / 2
            color: liveMarker && Boolean(liveMarker["out_of_bounds"]) ? window.palette.danger : window.palette.accent
            border.color: window.palette.text; border.width: 2
            Label { anchors.centerIn: parent; text: "•"; color: window.palette.text; font.pixelSize: 16; font.bold: true }
        }
        Label { objectName: "liveEnvelopeMarkerState"; visible: parent.showEnvelope; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 14; text: appViewModel ? appViewModel.envelope_marker_text : "MPos unknown"; color: appViewModel && Boolean(appViewModel.envelope_marker["out_of_bounds"]) ? window.palette.danger : window.palette.muted; font.pixelSize: 11; elide: Text.ElideRight }
        Connections { target: appViewModel; function onPreview_changed() { canvas.requestPaint() } function onState_changed() { canvas.requestPaint() } function onPosition_changed() { canvas.requestPaint() } }
        Label {
            objectName: "toolpathUnavailableNotice"
            visible: !toolpathCanvas.showEnvelope && (toolpathCanvas.showJob || toolpathCanvas.modeLabel === "PREPARE") && (!appViewModel || (appViewModel.preview_strokes.length === 0 && appViewModel.preview_image_url.length === 0))
            anchors.centerIn: parent
            width: Math.min(parent.width - 48, 360)
            text: appViewModel && appViewModel.job_file !== "No G-code loaded" ? "Job loaded · preview unavailable\nReview the job's separate toolpath evidence." : "No toolpath preview\nLoad or create a job to begin."
            color: window.palette.muted
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
        }
        Row { anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 14; spacing: 8
            Pill { label: parent.parent.modeLabel; tone: window.palette.accent }
            Pill { visible: parent.parent.showEnvelope; label: "Virtual envelope"; tone: window.palette.warning }
            Pill { visible: !parent.parent.showEnvelope && appViewModel && appViewModel.preview_image_url.length > 0 && !(parent.parent.showJob && appViewModel.preview_path_layers_available); label: "All moves · raster"; tone: window.palette.accent }
            Pill { visible: !parent.parent.showEnvelope && parent.parent.showJob && appViewModel && appViewModel.preview_path_layers_available; label: "Separate cutting + rapid paths"; tone: window.palette.accent }
            Pill { visible: parent.parent.showJob && parent.parent.showCurrentLayer && appViewModel && appViewModel.program_execution_layer["state"] === "cutting_layer"; label: "Green · current cutting layer"; tone: window.palette.success }
        }
        Label {
            objectName: "largeJobRasterPreviewNote"
            visible: !toolpathCanvas.showEnvelope && appViewModel && appViewModel.preview_image_note.length > 0
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 14
            width: Math.min(parent.width * 0.52, 330)
            text: appViewModel ? appViewModel.preview_image_note : ""
            color: window.palette.muted
            font.pixelSize: 10
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignRight
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
            Label { visible: !parent.parent.showJob || parent.parent.showCuttingPath; text: "— Cutting path"; color: window.palette.accent; font.pixelSize: 11 }
            Label { visible: (!parent.parent.showJob || parent.parent.showRapidPaths) && appViewModel && (appViewModel.preview_rapid_strokes.length > 0 || appViewModel.preview_rapid_image_url.length > 0); text: "— Rapid move"; color: "#F2B84B"; font.pixelSize: 11 }
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
