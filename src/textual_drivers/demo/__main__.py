import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Textual Drivers Demo")
    parser.add_argument(
        "--demo",
        choices=["check_image_support", "try_both", "kitty_drag_out", "kitty_drag_in"],
        default="check_image_support",
        help="Choose a demo to run",
    )
    args = parser.parse_args()

    if args.demo == "check_image_support":
        from .capability_check_app import CapabilityCheckApp

        CapabilityCheckApp().run()
    elif args.demo == "try_both":
        from .test_app import DriverTestApp

        DriverTestApp().run()
    elif args.demo == "kitty_drag_out":
        from .drag_out import DragOutApp

        DragOutApp().run()
    elif args.demo == "kitty_drag_in":
        from .drag_in import DragInApp

        DragInApp().run()


if __name__ == "__main__":
    main()
