import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Textual Drivers Demo")
    parser.add_argument("--demo", choices=["check_image_support", "try_both"], default="check_image_support", help="Choose a demo to run")
    args = parser.parse_args()

    if args.demo == "check_image_support":
        from .capability_check_app import CapabilityCheckApp, _Driver
        CapabilityCheckApp(driver_class=_Driver).run()
    elif args.demo == "try_both":
        from .test_app import DriverTestApp, _Driver
        DriverTestApp(driver_class=_Driver).run()

if __name__ == "__main__":
    main()
