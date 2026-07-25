# Python SDK Source Mirror Provenance

- **Public source/distribution mirror.**
- Package: `aigentsy`
- Published version: `1.16.0`
- Implementation source subtree: `sdk/aigentsy`
- Release source commit: `ad8373d77ac9babe8b406d2bc50b15f33ab2671a`
- Verified unchanged through runtime commit: `c05759b5eb34abad82ea530e85fa0a2e56dcd84b`
- Published wheel: `aigentsy-1.16.0-py3-none-any.whl`
  - SHA-256: `ada6fb50a72063ea0ae8e8e29dab27a7805e2dd6e9bb983b41dc76548cb86b08`
- Published sdist: `aigentsy-1.16.0.tar.gz`
  - SHA-256: `3340737815e5ee136f2e78d605ceaddb82eb417e6b529987f3f7de216cc21112`
- Sync pass: `PASS 30-Z-C3A`

The 31 mirrored release-source files below are exact raw-byte copies of the
release source. **PyPI remains the published distribution authority**; the
runtime and protocol contracts remain the behavioral authorities. This mirror
creates no new package, runtime, or protocol authority — it provides source
visibility only. Drift should be reported through this repository's existing
issue mechanism.

- Total mirrored source files: **31**
- Files modified from prior public mirror: **7**
- Files added to prior public mirror: **24**
- Files removed: **0**

## Standalone test context

The mirrored tests under `sdk/aigentsy/tests/` are byte-identical to the
published 1.16.0 release source. All **185** tests pass in the expected
runtime-monorepo layout (where the SDK sits alongside the runtime's `prompts/`
directory). In a standalone checkout of *this* public repository,
`python -m pytest sdk/aigentsy/tests/` yields **183 passed, 2 failed, 0 skipped**.

The two failing tests are:

- `test_cli_create_agent.py::test_bundled_canonical_prompt_matches_runtime_canonical_byte_for_byte`
- `test_cli_create_agent.py::test_generated_prompt_matches_canonical_byte_for_byte`

Both expect the runtime-only file `prompts/settlement_native_agent_system_prompt.md`
located above the SDK project (`REPO_ROOT/prompts/...`). That prompt is **not**
part of the Python SDK source mirror or the published package implementation, so
it is intentionally absent here. No SDK source or test has been altered to
conceal or bypass this dependency. The two failures do **not** affect package
installation, public API behavior, wheel construction, lifecycle wrappers,
signing support, or canonical example execution.

## Source manifest (SHA-256 of raw file bytes, relative to `sdk/aigentsy/`)

```
cf286f2a00b9c0a40f0e10186a1a20b75d34697e7a1298e99b091f237fa7452b  CHANGELOG.md
13baa1024d1a9570903df459dbc54e7b47e63c3399338cdb7a432193fc722bb3  LICENSE
6f2a4afe40d6df9f18b0523f1e4cdf1004c92c68448fd3302bad99a2e4d1e0ce  README.md
0f7aa8f4869a13a669150d43e4b77d0523bc28f4652adc6af6896cdf4b284430  examples/canonical_consequence_lifecycle.py
1e75801f8fa7870b256e1736443bb86756b2f09743513ef9d1d158bc502f1cce  examples/non_payout_gate_and_prove.py
e32fc7da4726e0dda6a9b8eb725787e530da0db8572b30a82c76c81243854e38  pyproject.toml
effea04c8a8b092eba6e6a8a3f901318a119112443967fd83d2d4570342a4b8c  src/aigentsy/__init__.py
3b5595e365c3bcfff0b4ecc2ddc50e32fb95c2a7885291c414e6b1dd43aa8e3c  src/aigentsy/__main__.py
269198a40c530f9ab2679609599bdbcdf2e76e3343e652611949d178b47ad37e  src/aigentsy/cli.py
f3fbbcc9b6b83066377a6f3c30739368a0803871456df1465bee3556142e2162  src/aigentsy/client.py
7cf9d4d6e9034d3fea3e9f8896301b6ed4c7ce78a46896fc187abf5a7fddd0dc  src/aigentsy/gate.py
ad8ddf20f48c16aaa48f14b1628d7bd1bb804efeec8b1092f9d6347e711049b3  src/aigentsy/keypair.py
de1de65e29be8030be34b45117566cdca22165ae525578edd18dbbdf0f1baa45  src/aigentsy/templates/__init__.py
979719c4ff1c255ade01df170f8db185c84c4822697d35d39d040e74b1a28384  src/aigentsy/templates/settlement_native_mcp/README.md.template
39826cd1edf98d9050a9f97e10ddf6ed2b0d1fb015c0962d206d545b73b3fad6  src/aigentsy/templates/settlement_native_mcp/acceptance_policy.example.json
b698ffd1028b809395ffd672104740a6e95ceae2f95658db736c468065c55e2f  src/aigentsy/templates/settlement_native_mcp/adapter_contract.example.json
f19345535bf7c0135f1c10943e3f7284725fe8695ff7003535b730d87a01047d  src/aigentsy/templates/settlement_native_mcp/agent.py.template
af1e6ff4be466f27aa6e369e35b4de1bcca587d73f2ab8da33ad26bff59d957c  src/aigentsy/templates/settlement_native_mcp/agent_system_prompt.md
5107d60c1ead254dbe479c7e4e3aeb20bbbc8162f3274acfca054cbfab264168  src/aigentsy/templates/settlement_native_mcp/lifecycle.md
6f79818ba15c6941f2015acdbb186a3cd79099a8f900e8ab154de721618a31a5  src/aigentsy/templates/settlement_native_mcp/mcp_config.example.json
cf9f30f69cacde9a4d2892694f524f244476e88c5c8b2f49813a1b5bfcc638f4  src/aigentsy/templates/settlement_native_mcp/tests/test_settlement_lifecycle.py.template
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  tests/__init__.py
4cf122c2977354eade697b65b4eef9618cc0f9ade1d359a10f6297bd248f3431  tests/test_cli_admin_account.py
3cfd9ac8333e5d645b684075301ab150d78e03b41ebb5bf3a00bed46e987eb1e  tests/test_cli_admin_account_membership.py
bea5c763c317701ee83919597a43b9d0147abd1207baf75f1383f89f83912478  tests/test_cli_admin_owner_bound.py
c75df48f226e8f3f1a15c53f5756ef0edce5089232cb8d0e90b29f5eab22602c  tests/test_cli_create_agent.py
219925aee413f6713f28ea98a937304fdb3923c42726324ed26184a7ba5dd065  tests/test_gate_and_prove.py
cc94305e397ce32cc81fa61ee7f7b2d8fd6e2e48d0aa0e102b47f5a141c8504b  tests/test_lifecycle_wrappers.py
0efd2c716ff7e04ce0240e5c715773b12e74760a876895c0f96bcba41e651d40  tests/test_public_api_surface.py
269bdad7843177126ad276ad8d1c43ca26c7b3f27b5f8e7515831ed81bdf1c56  tests/test_record_outcome_reconciled.py
bf6ca6f60518e62de06c7b09fc9c2be1f2da0b9584a0e7572bbe53ae2343b5d4  tests/test_signing_keypair.py
```
