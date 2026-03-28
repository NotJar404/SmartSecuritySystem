using Microsoft.AspNetCore.Mvc;
using System.Security.Claims;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;

namespace SmartSecuritySystem.Controllers
{
    public class AuthController : Controller
    {
        // GET
        public IActionResult Login()
        {
            return View();
        }

        // POST
        [HttpPost]
        public async Task<IActionResult> Login(string username, string password)
        {
            string role = null;

            // TEMP LOGIN (replace with DB later)
            if (username == "admin" && password == "1234")
                role = "Admin";
            else if (username == "security" && password == "1234")
                role = "Security";

            if (role != null)
            {
                // 🔥 CREATE CLAIMS
                var claims = new List<Claim>
                {
                    new Claim(ClaimTypes.Name, username),
                    new Claim(ClaimTypes.Role, role) // ⭐ THIS FIXES EVERYTHING
                };

                var identity = new ClaimsIdentity(
                    claims,
                    CookieAuthenticationDefaults.AuthenticationScheme);

                var principal = new ClaimsPrincipal(identity);

                // 🔥 SIGN IN
                await HttpContext.SignInAsync(
                    CookieAuthenticationDefaults.AuthenticationScheme,
                    principal);

                // 🔁 REDIRECT
                if (role == "Admin")
                    return RedirectToAction("Index", "Admin");
                else
                    return RedirectToAction("Index", "Dashboard");
            }

            ViewBag.Error = "Invalid credentials";
            return View();
        }

        public async Task<IActionResult> Logout()
        {
            await HttpContext.SignOutAsync();
            return RedirectToAction("Login");
        }
    }
}