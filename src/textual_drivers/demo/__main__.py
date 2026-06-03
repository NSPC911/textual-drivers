import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Textual Drivers Demo")
    parser.add_argument(
        "--demo",
        choices=["check_image_support", "try_both", "kitty_drag_out"],
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


if __name__ == "__main__":
    main()
