# Run all data-driven tests
pytest tests/test_all_flows_comprehensive.py -v

# Run only search flow with all data
pytest tests/test_all_flows_comprehensive.py::TestAllFlows::test_flow_search_only -v

# Run only complete flows
pytest tests/test_all_flows_comprehensive.py::TestAllFlows::test_flow_complete -v

# Run stepper tests only
pytest tests/test_all_flows_comprehensive.py -k "stepper" -v