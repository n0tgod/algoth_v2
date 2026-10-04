import SwiftUI
import UIKit

/// Касания графика внутри прокручиваемой страницы — распознавателями UIKit.
///
/// Жесты SwiftUI здесь не годились: удержание срабатывало в момент
/// касания (вибрация при попытке листать) и забирало палец у прокрутки
/// страницы. Распознаватели UIKit умеют уступать: пока палец движется
/// раньше срока удержания, страница листается как обычно.
///
/// - удержание 0.35 с без движения — выбор (с толчком), затем ведение
///   пальцем; прокрутка страницы на это время выключена;
/// - щипок — масштаб;
/// - горизонтальный свайп — сдвиг (только если `panEnabled`).
struct ChartTouchLayer: UIViewRepresentable {
    var panEnabled: Bool
    var onPick: (CGFloat) -> Void          // x в координатах слоя
    var onPickEnd: () -> Void
    var onPinch: (_ scale: CGFloat, _ anchorX: CGFloat, _ ended: Bool) -> Void
    var onPan: (_ dx: CGFloat, _ ended: Bool) -> Void

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> UIView {
        let v = UIView()
        v.backgroundColor = .clear
        let c = context.coordinator
        let lp = UILongPressGestureRecognizer(target: c, action: #selector(Coordinator.long(_:)))
        lp.minimumPressDuration = 0.35
        lp.allowableMovement = 8
        lp.delegate = c
        let pinch = UIPinchGestureRecognizer(target: c, action: #selector(Coordinator.pinch(_:)))
        pinch.delegate = c
        let pan = UIPanGestureRecognizer(target: c, action: #selector(Coordinator.pan(_:)))
        pan.delegate = c
        pan.maximumNumberOfTouches = 1
        c.panRecognizer = pan
        [lp, pinch, pan].forEach(v.addGestureRecognizer)
        return v
    }

    func updateUIView(_ v: UIView, context: Context) {
        context.coordinator.parent = self
    }

    final class Coordinator: NSObject, UIGestureRecognizerDelegate {
        var parent: ChartTouchLayer?
        weak var panRecognizer: UIPanGestureRecognizer?
        private let thump = UIImpactFeedbackGenerator(style: .medium)
        private weak var scroll: UIScrollView?

        @objc func long(_ g: UILongPressGestureRecognizer) {
            guard let view = g.view else { return }
            let x = g.location(in: view).x
            switch g.state {
            case .began:
                thump.impactOccurred()
                // Пока ведём выбор, страница стоит: иначе вертикальный
                // дрейф пальца листал бы её под графиком.
                scroll = enclosingScroll(view)
                scroll?.isScrollEnabled = false
                parent?.onPick(x)
            case .changed:
                parent?.onPick(x)
            default:
                scroll?.isScrollEnabled = true
                parent?.onPickEnd()
            }
        }

        @objc func pinch(_ g: UIPinchGestureRecognizer) {
            guard let view = g.view else { return }
            let ax = g.numberOfTouches > 0 ? g.location(in: view).x / max(view.bounds.width, 1) : 0.5
            let ended = g.state == .ended || g.state == .cancelled || g.state == .failed
            parent?.onPinch(g.scale, ax, ended)
        }

        @objc func pan(_ g: UIPanGestureRecognizer) {
            guard let view = g.view else { return }
            let ended = g.state == .ended || g.state == .cancelled || g.state == .failed
            parent?.onPan(g.translation(in: view).x, ended)
        }

        func gestureRecognizerShouldBegin(_ g: UIGestureRecognizer) -> Bool {
            if let p = g as? UIPanGestureRecognizer, p === panRecognizer {
                // Сдвиг — только в приближении и только по горизонтали:
                // вертикальное движение остаётся прокрутке страницы.
                guard parent?.panEnabled == true else { return false }
                let v = p.velocity(in: p.view)
                return abs(v.x) > abs(v.y) * 1.5
            }
            return true
        }

        // Прокрутка страницы и наши распознаватели живут вместе: страница
        // листается, пока удержание не сработало.
        func gestureRecognizer(_ g: UIGestureRecognizer,
                               shouldRecognizeSimultaneouslyWith o: UIGestureRecognizer) -> Bool {
            !(g is UILongPressGestureRecognizer && o is UIPinchGestureRecognizer)
        }

        private func enclosingScroll(_ v: UIView) -> UIScrollView? {
            var s = v.superview
            while let cur = s {
                if let sv = cur as? UIScrollView { return sv }
                s = cur.superview
            }
            return nil
        }
    }
}
