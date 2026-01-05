# Contributing to SAS Field Lineage Tracker

Thank you for your interest in contributing! This document provides guidelines for contributing to the project.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/sas-field-lineage.git`
3. Create a branch: `git checkout -b feature/your-feature-name`
4. Install dependencies: `pip install -r requirements.txt`
5. Install in development mode: `pip install -e .`

## Development Setup

```bash
# Install development dependencies
pip install -r requirements.txt
pip install -e .

# Run tests
python -m unittest discover tests/

# Run the demo
python examples/demo.py

# Test CLI
python -m sas_lineage.cli examples/sales_analysis.sas -b
```

## Making Changes

### Code Style

- Follow PEP 8 style guidelines
- Use type hints where appropriate
- Write docstrings for all public functions and classes
- Keep functions focused and modular

### Testing

- Write tests for new features
- Ensure all existing tests pass
- Test with various SAS code patterns
- Test edge cases

### Documentation

- Update README.md if adding features
- Add examples to demonstrate new functionality
- Update API_USAGE.md for API changes
- Document any limitations or known issues

## Pull Request Process

1. Update documentation as needed
2. Add tests for new functionality
3. Ensure all tests pass
4. Update CHANGELOG.md with your changes
5. Submit a pull request with a clear description

### PR Description Template

```
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Performance improvement

## Testing
How was this tested?

## Checklist
- [ ] Tests pass
- [ ] Documentation updated
- [ ] Code follows style guidelines
```

## Areas for Contribution

### High Priority

1. **Parser Improvements**
   - Support for more SAS statements
   - Better handling of PROC steps
   - Macro variable expansion
   - Array processing

2. **Lineage Features**
   - Cross-file lineage tracking
   - Database connection support
   - Data quality lineage
   - Column-level transformations

3. **UI Enhancements**
   - Interactive graph visualization
   - Search and filter improvements
   - Export to various formats
   - Dark mode

4. **Performance**
   - Large file handling
   - Caching strategies
   - Parallel processing
   - Memory optimization

### Good First Issues

- Add more example SAS files
- Improve error messages
- Add unit tests for edge cases
- Documentation improvements
- Fix typos and formatting

## Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Focus on what is best for the project
- Show empathy towards other contributors

## Questions?

Feel free to open an issue for:
- Bug reports
- Feature requests
- Questions about usage
- Suggestions for improvement

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

## References

- [SAS Documentation](https://support.sas.com/)
- [Python Style Guide (PEP 8)](https://pep8.org/)
- [Semantic Versioning](https://semver.org/)

Thank you for contributing! 🎉
