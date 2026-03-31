using Microsoft.AspNetCore.Http;
using SmartSecuritySystem.Models;
using System;
using System.Collections.Generic;
using System.Linq;

namespace WebApp.Services
{
    public class AuthService
    {
        // 🔥 In-memory user list for testing
        private readonly List<User> _users;

        public AuthService()
        {
            _users = new List<User>
            {
                new User
                {
                    Id = 1,
                    Username = "admin",
                    PasswordHash = "1234", // plain text for testing
                    Role = "Admin",
                    Name = "System Administrator",
                    Email = "admin@email.com",
                    Status = "Active"
                },
                new User
                {
                    Id = 2,
                    Username = "security",
                    PasswordHash = "1234", // plain text for testing
                    Role = "Security",
                    Name = "Security Personnel",
                    Email = "security@email.com",
                    Status = "Active"
                }
            };
        }

        // =========================
        // VALIDATE LOGIN
        // =========================
        public (bool success, User user) ValidateUser(string username, string password)
        {
            var user = _users.FirstOrDefault(u => u.Username.Equals(username, StringComparison.OrdinalIgnoreCase));
            if (user == null) return (false, null);

            if (VerifyPassword(user, password))
            {
                return (true, user);
            }

            return (false, null);
        }

        // =========================
        // GET CURRENT USER FROM SESSION
        // =========================
        public User GetCurrentUser(HttpContext context)
        {
            var userId = context.Session.GetInt32("UserId");
            if (userId == null) return null;

            return _users.FirstOrDefault(u => u.Id == userId.Value);
        }

        // =========================
        // VERIFY PASSWORD
        // =========================
        public bool VerifyPassword(User user, string password)
        {
            return user.PasswordHash == password; // ⚠️ plain text for testing only
        }

        // =========================
        // UPDATE PASSWORD
        // =========================
        public void UpdatePassword(int userId, string newPassword)
        {
            var user = _users.FirstOrDefault(u => u.Id == userId);
            if (user == null) return;

            user.PasswordHash = newPassword; // ⚠️ plain text
        }

        // =========================
        // CHECK IF EMAIL EXISTS
        // =========================
        public bool EmailExists(string email)
        {
            return _users.Any(u => u.Email.Equals(email, StringComparison.OrdinalIgnoreCase));
        }

        // =========================
        // GENERATE RESET TOKEN
        // =========================
        public string GenerateResetToken()
        {
            return Guid.NewGuid().ToString();
        }

        // =========================
        // RESET PASSWORD (TEMP)
        // =========================
        public bool ResetPassword(string token, string newPassword)
        {
            // 🔥 TEMP: just reset admin password for testing
            var user = _users.FirstOrDefault(u => u.Username == "admin");
            if (user == null) return false;

            user.PasswordHash = newPassword;
            return true;
        }
    }
}